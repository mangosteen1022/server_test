"""邮件同步管理器 - 重构版，完全基于 group_id"""
import json
import re
import traceback
from typing import Dict, List, Any, Optional, Callable

from auth.msal_client import MSALClient
from celery_app import RedisKeys
from utils.time_utils import utc_now, utc_days_ago
from database.factory import get_db
import redis, settings

redis_client = redis.from_url(settings.REDIS_URL)


class MailSyncManager:
    """邮件同步管理器"""

    def sync_folders(self, group_id: str, msal_client: MSALClient) -> Dict[str, Any]:
        """
        同步完整文件夹目录树(不含隐藏文件夹，含子文件夹)
        """
        try:
            root_resp = msal_client.list_mail_folders(top=100)
            root_folders = root_resp.get("value", [])
            if not root_folders:
                return {"success": True, "count": 0, "message": "无文件夹"}
            folder_queue = list(root_folders)
            i = 0
            while i < len(folder_queue):
                current_folder = folder_queue[i]
                i += 1
                child_count = current_folder.get("childFolderCount", 0)
                f_id = current_folder.get("id")
                if child_count > 0 and f_id:
                    try:
                        child_resp = msal_client.list_child_folders(f_id, top=100)
                        children = child_resp.get("value", [])
                        if children:
                            folder_queue.extend(children)
                    except Exception as e:
                        print(f"获取子文件夹失败 {f_id}: {e}")

            # 3. 批量写入数据库
            total_synced = 0
            with get_db() as db:
                for folder in folder_queue:
                    folder_id = folder.get("id")
                    display_name = folder.get("displayName")
                    parent_id = folder.get("parentFolderId")
                    well_known = folder.get("wellKnownName")
                    total_count = folder.get("totalItemCount")
                    unread_count = folder.get("unreadItemCount")
                    updated_at = str(utc_now())
                    db.execute("""
                               INSERT INTO mail_folders (folder_id, group_id, display_name, well_known_name,
                                                         parent_folder_id, total_count, unread_count, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(folder_id) DO UPDATE SET display_name=excluded.display_name,
                                                                    parent_folder_id=excluded.parent_folder_id,
                                                                    total_count=excluded.total_count,
                                                                    unread_count=excluded.unread_count,
                                                                    updated_at = excluded.updated_at
                               """,
                               (folder_id, group_id, display_name, well_known, parent_id, total_count, unread_count,
                                updated_at))
                    total_synced += 1
                db.commit()

            return {
                "success": True,
                "count": total_synced,
                "message": f"目录同步完成 (根目录+子目录 共{total_synced}个)"
            }

        except Exception as e:
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def sync_group_mails(
            self,
            group_id: str,
            msal_client: MSALClient,
            strategy: str = "auto",
            cb: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        同步邮箱组邮件（主入口）

        Args:
            group_id: 邮箱组ID
            msal_client: MSAL客户端实例
            strategy: 同步策略
                - "auto": 自动选择（优先delta > incremental > recent）
                - "full": 完整同步所有邮件
                - "delta": 强制使用 Delta 同步
                - "incremental": 增量同步（基于时间）
                - "recent": 同步最近的邮件
                - "check": 仅保活检查
            cb: 进度回调函数 (group_id, message)

        Returns:
            {
                "success": bool,
                "error": str (如果失败),
                "synced": int (同步数量),
                "total_fetched": int (获取总数),
                "sync_state": dict (同步状态)
            }
        """
        try:
            # 1. 获取同步状态
            folders = self._get_local_folders(group_id)
            if not folders:
                return {"success": False, "error": "未找到本地文件夹记录，请先执行目录同步", "synced": 0}
            if cb:
                cb(group_id, f"开始同步邮件 (策略: {strategy})")
            total_synced = 0
            total_fetched = 0
            errors = []
            sync_start_time = utc_now()
            for folder in folders:
                f_name = folder["display_name"]
                if folder["total_count"] == 0:
                    continue
                if cb:
                    cb(group_id, f"正在同步: {f_name}")
                try:
                    args = (group_id, msal_client, folder, sync_start_time, cb)
                    if strategy == "full":
                        res = self._sync_folder_full(*args)
                    elif strategy == "recent":
                        res = self._sync_folder_recent(*args)
                    else:  # auto
                        if folder["delta_link"]:
                            res = self._sync_folder_delta(*args)
                        elif folder["last_sync_at"]:
                            res = self._sync_folder_incremental(*args)
                        else:
                            res = self._sync_folder_recent(*args)

                    total_synced += res.get("synced", 0)
                    total_fetched += res.get("fetched", 0)

                except Exception as e:
                    err_msg = f"文件夹 {f_name} 同步失败: {str(e)}"
                    errors.append(err_msg)
                success_msg = f"同步完成，共入库 {total_synced} 封"
                if errors:
                    success_msg += f" (有 {len(errors)} 个错误)"

                if cb:
                    cb(group_id, success_msg)
                return {
                    "success": len(errors) == 0,
                    "synced": total_synced,
                    "total_fetched": total_fetched,
                    "errors": errors,
                    "message": f"同步完成，共入库 {total_synced} 封"
                }
        except Exception as e:
            traceback.print_exc()
            return {"success": False, "error": str(e), "synced": 0}

    @staticmethod
    def _get_local_folders(group_id: str) -> List[Dict[str, Any]]:
        """
        从本地数据库加载文件夹映射
        Return: { "Graph_Folder_ID": Local_DB_ID }
        """
        with get_db() as db:
            rows = db.execute(
                "SELECT * FROM mail_folders WHERE group_id = ?",
                (group_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _update_folder_state(folder_id: str, data: Dict):
        """更新文件夹同步状态"""
        # 动态构建 SET 语句
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        params = list(data.values())
        params.append(folder_id)

        with get_db() as db:
            db.execute(
                f"UPDATE mail_folders SET {set_clause} WHERE folder_id = ?",
                params
            )
            db.commit()

    def _sync_folder_delta(self, group_id: str, client: MSALClient, folder: Dict, sync_time: str, cb) -> Dict:
        """策略：Delta 同步 (最高效)"""
        folder_id = folder["folder_id"]
        delta_link = folder["delta_link"]
        folder_name = folder["display_name"]

        total_synced = 0
        new_delta_link = None

        # 1. 循环获取变更页
        while delta_link:  # TODO 详细进度
            if cb: cb(group_id, f"同步 {folder_name}: 获取变更中...")
            resp = client.get_messages_delta(delta_link=delta_link, folder_id=folder_id)
            mails = resp.get("value", [])

            # 保存数据
            if mails:
                count = self.save_mails_to_db(group_id, mails)
                total_synced += count

            # 获取下一页或新的 deltaLink
            delta_link = resp.get("@odata.nextLink")
            new_delta_link = resp.get("@odata.deltaLink")

            # 如果拿到了 deltaLink，说明本轮结束
            if new_delta_link:
                break

        # 2. 更新文件夹状态
        if new_delta_link:
            self._update_folder_state(folder_id, {
                "delta_link": new_delta_link,
                "last_sync_at": sync_time,
                "synced_count": folder["synced_count"] + total_synced
            })

        return {"synced": total_synced, "fetched": total_synced}

    def _sync_folder_incremental(self, group_id: str, client: MSALClient, folder: Dict, sync_time: str, cb) -> Dict:
        """策略：增量同步 (基于时间窗)"""
        last_sync = folder["last_sync_at"]
        filter_str = f"receivedDateTime gt {last_sync}"

        return self._fetch_and_save_pages(
            group_id, client, folder,
            filter_str=filter_str,
            sync_time_to_update=sync_time,
            cb=cb
        )

    def _sync_folder_recent(self, group_id: str, client: MSALClient, folder: Dict, sync_time: str, cb) -> Dict:
        """策略：最近邮件 (默认30天)"""
        start_date = utc_days_ago(30)
        filter_str = f"receivedDateTime gt {start_date}"

        return self._fetch_and_save_pages(
            group_id, client, folder,
            filter_str=filter_str,
            sync_time_to_update=sync_time,
            try_enable_delta=True,
            cb=cb
        )

    def _sync_folder_full(self, group_id: str, client: MSALClient, folder: Dict, sync_time: str, cb) -> Dict:
        """策略：全量同步"""
        return self._fetch_and_save_pages(
            group_id, client, folder,
            filter_str=None,
            sync_time_to_update=sync_time,
            try_enable_delta=True,
            cb=cb
        )

    def _fetch_and_save_pages(
            self,
            group_id: str,
            client: MSALClient,
            folder: Dict,
            filter_str: Optional[str],
            sync_time_to_update: str,
            try_enable_delta: bool = False,
            cb: Callable = None
    ) -> Dict:
        """通用分页拉取与保存逻辑"""
        # TODO 详细进度同步
        folder_id = folder["folder_id"]
        total_synced = 0
        total_fetched = 0

        skip_token = None

        batch_limit = 50  # 安全限制：防止无限循环
        batch_count = 0

        while batch_count < batch_limit:
            resp = client.list_messages(
                folder_id=folder_id,
                top=50,
                filter_str=filter_str,
                orderby="receivedDateTime desc",
                skip_token=skip_token,
                select=[
                    "id", "subject", "from", "toRecipients", "ccRecipients",
                    "receivedDateTime", "sentDateTime", "isRead", "hasAttachments",
                    "bodyPreview", "internetMessageId", "parentFolderId",
                ]
            )

            mails = resp.get("value", [])
            if not mails:
                break

            count = self.save_mails_to_db(group_id, mails, cb)
            total_synced += count
            total_fetched += len(mails)

            # 下一页
            next_link = resp.get("@odata.nextLink")
            if next_link:
                # 简单解析 skipToken
                match = re.search(r"\$skiptoken=([^&]+)", next_link)
                skip_token = match.group(1) if match else None
                if not skip_token: break  # 防御，避免死循环
            else:
                break

            batch_count += 1

        # 更新文件夹状态
        update_data = {
            "last_sync_at": sync_time_to_update,
            "synced_count": (folder["synced_count"] or 0) + total_synced
        }

        # 如果需要开启 Delta (通常在首次同步后)，尝试请求一次 Delta Link 以备下次使用
        # 只有当本次拉取成功且有数据时才尝试
        if try_enable_delta:
            try:
                # 请求一个空的 delta 哪怕不拿数据，只为了拿到 Link
                # 注意：这里需要捕获异常，因为某些文件夹可能不支持 Delta
                delta_resp = client.get_messages_delta(folder_id=folder_id)
                if "@odata.deltaLink" in delta_resp:
                    update_data["delta_link"] = delta_resp["@odata.deltaLink"]
            except Exception:
                pass  # 忽略 Delta 获取失败，回退到基于时间同步

        self._update_folder_state(folder_id, update_data)

        return {"synced": total_synced, "fetched": total_fetched}

    def save_mails_to_db(
            self,
            group_id: str,
            mails: List[Dict],
            progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> int:
        """
        [重写] 将邮件数据序列化并推送到 Redis 队列
        """
        if not mails:
            return 0
        items_to_push = []

        for mail in mails:
            try:
                flags_list = []
                if mail.get("isRead"): flags_list.append("Read")
                if mail.get("flag", {}).get("flagStatus") == "flagged": flags_list.append("Flagged")
                flags_str = ";".join(flags_list) if flags_list else "UNREAD"

                has_attachments = 1 if mail.get("hasAttachments") else 0
                to_recipients = [r.get("emailAddress", {}).get("address", "") for r in mail.get("toRecipients", [])]
                to_joined = ",".join(filter(None, to_recipients))
                msg_payload = {
                    "table": "mail_message",
                    "data": {
                        "group_id": group_id,
                        "msg_uid": mail.get("id"),
                        "msg_id": mail.get("internetMessageId"),
                        "subject": mail.get("subject", ""),
                        "from_addr": mail.get("from", {}).get("emailAddress", {}).get("address", ""),
                        "from_name": mail.get("from", {}).get("emailAddress", {}).get("name", ""),
                        "to_joined": to_joined,
                        "snippet": mail.get("bodyPreview", ""),
                        "folder_id": mail.get("parentFolderId"),
                        "sent_at": mail.get("sentDateTime"),
                        "received_at": mail.get("receivedDateTime"),
                        "size_bytes": mail.get("size", 0),
                        "has_attachments": has_attachments,  # 0 或 1
                        "flags": flags_str,
                        "created_at": str(utc_now()),
                        "updated_at": str(utc_now())
                    }
                }

                # 序列化为 JSON 字符串 (default=str 处理 datetime 对象)
                items_to_push.append(json.dumps(msg_payload, default=str))

            except Exception as e:
                # 打印日志但不中断循环，防止单封邮件格式错误导致整批失败
                print(f"Async prepare failed for mail {mail.get('id', 'unknown')}: {e}")
                continue

        # 3. 批量推送到 Redis (使用 Pipeline 提高性能)
        if items_to_push:
            try:
                pipe = redis_client.pipeline()
                for item in items_to_push:
                    pipe.lpush(RedisKeys.DB_WRITE_QUEUE, item)
                pipe.execute()
                # 触发进度回调
                if progress_callback:
                    progress_callback(group_id, f"已缓冲 {len(items_to_push)} 封")

                return len(items_to_push)
            except Exception as e:
                print(f"Redis push failed: {e}")
                return 0

        return 0
