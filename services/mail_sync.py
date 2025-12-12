"""邮件同步管理器 - 重构版，完全基于 group_id"""

import sqlite3
import re
import traceback
from typing import Dict, List, Any, Optional, Callable

from auth.msal_client import MSALClient
from utils.time_utils import utc_now, utc_days_ago
from database.factory import get_db


class MailSyncManager:
    """邮件同步管理器"""

    def sync_group_mails(
        self,
        group_id: str,
        msal_client: MSALClient,
        strategy: str = "auto",
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        同步邮箱组邮件（主入口）

        Args:
            group_id: 邮箱组ID
            msal_client: MSAL客户端实例
            strategy: 同步策略
                - "auto": 自动选择（优先delta > incremental > recent）
                - "full": 完整同步所有邮件
                - "incremental": 增量同步（基于时间）
                - "recent": 同步最近的邮件
            progress_callback: 进度回调函数 (group_id, message)

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
            return self._sync_group_mails_with_db(
                group_id=group_id,
                msal_client=msal_client,
                strategy=strategy,
                progress_callback=progress_callback
            )
        except Exception as e:
            traceback.print_exc()
            return {"success": False, "error": str(e), "synced": 0}

    def _sync_group_mails_with_db(
        self,
        group_id: str,
        msal_client: MSALClient,
        strategy: str = "auto",
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """内部方法，使用已存在的数据库连接"""
        try:
            # 1. 获取同步状态
            sync_state = self.get_sync_state(group_id)

            if progress_callback:
                progress_callback(group_id, f"开始同步邮件 (策略: {strategy})")

            # 同步文件夹到数据库
            self._sync_folders_to_db(group_id, msal_client)

            # 2. 根据策略选择同步方式
            if strategy == "auto":
                if sync_state.get("delta_link"):
                    result = self.sync_with_delta(group_id, msal_client, sync_state, progress_callback)
                elif sync_state.get("last_sync_time"):
                    result = self.sync_incremental(group_id, msal_client, sync_state, progress_callback)
                else:
                    result = self.sync_recent(group_id, msal_client, progress_callback)
            elif strategy == "full":
                result = self.sync_full(group_id, msal_client, sync_state, progress_callback)
            elif strategy == "incremental":
                result = self.sync_incremental(group_id, msal_client, sync_state, progress_callback)
            else:  # recent
                result = self.sync_recent(group_id, msal_client, progress_callback)

            # 3. 更新同步状态
            if result.get("success"):
                self.update_sync_state(group_id, result.get("sync_state", {}))

            return result

        except Exception as e:
            traceback.print_exc()
            return {"success": False, "error": str(e), "synced": 0}

    def _sync_folders_to_db(self, group_id: str, msal_client: MSALClient) -> int:
        """同步文件夹到数据库"""
        try:
            with get_db() as db:
                response = msal_client.list_mail_folders()
                folders = response.get("value", [])
                if not folders:
                    return 0

                folder_data = []
                for folder in folders:
                    try:
                        folder_id = folder["id"]
                        folder_name = folder.get("displayName", "Unknown")
                        parent_id = folder.get("parentFolderId")
                        folder_data.append((folder_id, group_id, folder_name, parent_id))
                    except Exception as e:
                        print(f"准备文件夹数据失败: {e}")
                        continue

                if folder_data:
                    db.executemany("""
                        INSERT OR REPLACE INTO mail_folder (
                            id, group_id, display_name, parent_folder_id
                        ) VALUES (?, ?, ?, ?)
                    """, folder_data)
                    db.commit()

                return len(folder_data)
        except Exception as e:
            print(f"同步文件夹失败: {e}")
            return 0

    def get_sync_state(self, group_id: str) -> Dict[str, Any]:
        """获取同步状态"""
        try:
            with get_db() as db:
                row = db.execute("SELECT * FROM mail_sync_state WHERE group_id = ?", (group_id,)).fetchone()
                if row:
                    return dict(row)
                else:
                    return {}
        except Exception as e:
            return {}

    def update_sync_state(self, group_id: str, state: Dict[str, Any]):
        """更新同步状态"""
        try:
            with get_db() as db:
                last_sync_time = state.get("last_sync_time")
                if last_sync_time and not last_sync_time.endswith("Z"):
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(last_sync_time.replace("Z", "+00:00"))
                        last_sync_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except (ValueError, AttributeError):
                        last_sync_time = utc_now()

                db.execute("""
                INSERT INTO mail_sync_state (
                    group_id, last_sync_time, last_msg_uid,
                    delta_link, skip_token, total_synced, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    last_sync_time = excluded.last_sync_time,
                    last_msg_uid = excluded.last_msg_uid,
                    delta_link = excluded.delta_link,
                    skip_token = excluded.skip_token,
                    total_synced = excluded.total_synced,
                    updated_at = excluded.updated_at
            """, (
                group_id,
                last_sync_time,
                state.get("last_msg_uid"),
                state.get("delta_link"),
                state.get("skip_token"),
                state.get("total_synced", 0),
                utc_now(),
            ))
                db.commit()
        except Exception as e:
            print(f"更新同步状态失败: {e}")

    def get_primary_account_id(self, group_id: str) -> Optional[int]:
        """获取组的主账号ID（用于显示进度）"""
        with get_db() as db:
            result = db.execute(
                "SELECT id FROM accounts WHERE group_id = ? ORDER BY id LIMIT 1",
                (group_id,)
            ).fetchone()
            return result["id"] if result else None

    def _get_all_folders(self, msal_client: MSALClient) -> List[Dict[str, Any]]:
        """获取所有邮件文件夹"""
        all_folders = []
        try:
            response = msal_client.list_mail_folders()
            folders = response.get("value", [])

            for folder in folders:
                folder_info = {
                    "id": folder["id"],
                    "name": folder.get("displayName", "Unknown"),
                    "total": folder.get("totalItemCount", 0),
                    "unread": folder.get("unreadItemCount", 0),
                }
                all_folders.append(folder_info)

            return all_folders
        except Exception as e:
            print(f"获取文件夹列表失败: {e}")
            return []

    def sync_with_delta(
        self,
        group_id: str,
        msal_client: MSALClient,
        sync_state: Dict,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """使用Delta查询同步"""
        primary_account_id = self.get_primary_account_id(group_id)

        if progress_callback:
            if primary_account_id:
                progress_callback(group_id, f"[账号{primary_account_id}] 使用Delta查询获取所有文件夹的变更...")

        all_folders = self._get_all_folders(msal_client)
        if not all_folders:
            return {"success": False, "error": "未找到文件夹", "synced": 0}

        total_synced = 0
        folder_delta_links = sync_state.get("folder_delta_links", {})
        new_folder_delta_links = {}

        for folder in all_folders:
            folder_id = folder["id"]
            folder_name = folder["name"]

            if folder["total"] == 0:
                continue

            if progress_callback:
                progress_callback(group_id, f"[账号{primary_account_id}] 同步文件夹: {folder_name} (Delta)")

            try:
                delta_link = folder_delta_links.get(folder_id)
                new_mails = []

                if delta_link:
                    response = msal_client.get_messages_delta(delta_link, folder_id=folder_id)
                else:
                    response = msal_client.get_messages_delta(folder_id=folder_id)

                mails = response.get("value", [])
                new_mails.extend(mails)

                # 处理分页
                batch_count = 1
                while "@odata.nextLink" in response and batch_count < 50:
                    response = msal_client.get_messages_delta(response["@odata.nextLink"])
                    mails = response.get("value", [])
                    new_mails.extend(mails)
                    batch_count += 1

                # 保存邮件
                if new_mails:
                    synced = self.save_mails_to_db(group_id, new_mails, progress_callback)
                    total_synced += synced

                # 保存该文件夹的 delta link
                new_delta_link = response.get("@odata.deltaLink")
                if new_delta_link:
                    new_folder_delta_links[folder_id] = new_delta_link

            except Exception as e:
                print(f"Delta 同步文件夹 {folder_name} 失败: {e}")
                continue

        return {
            "success": True,
            "synced": total_synced,
            "total_fetched": total_synced,
            "sync_state": {
                "folder_delta_links": new_folder_delta_links,
                "last_sync_time": utc_now(),
                "total_synced": sync_state.get("total_synced", 0) + total_synced,
            },
        }

    def sync_incremental(
        self,
        group_id: str,
        msal_client: MSALClient,
        sync_state: Dict,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """增量同步（基于时间）"""
        last_sync_time = sync_state.get("last_sync_time")
        if not last_sync_time:
            if progress_callback:
                progress_callback(group_id, "未找到上次同步时间，改为获取最近30天邮件")
            return self.sync_recent(group_id, msal_client, progress_callback)

        primary_account_id = self.get_primary_account_id(group_id)

        if progress_callback:
            if primary_account_id:
                progress_callback(group_id, f"[账号{primary_account_id}] 获取所有文件夹在 {last_sync_time} 之后的邮件...")

        all_folders = self._get_all_folders(msal_client)
        if not all_folders:
            return {"success": False, "error": "未找到文件夹", "synced": 0}

        total_synced = 0
        total_fetched = 0

        for folder in all_folders:
            folder_id = folder["id"]
            folder_name = folder["name"]

            if folder["total"] == 0:
                continue

            if progress_callback:
                progress_callback(group_id, f"[账号{primary_account_id}] 同步文件夹: {folder_name} (增量)")

            result = self._sync_folder_incremental(
                group_id, msal_client, folder_id, folder_name, last_sync_time, progress_callback
            )

            total_synced += result.get("synced", 0)
            total_fetched += result.get("fetched", 0)

        new_sync_time = utc_now()

        return {
            "success": True,
            "synced": total_synced,
            "total_fetched": total_fetched,
            "sync_state": {
                "last_sync_time": new_sync_time,
                "total_synced": sync_state.get("total_synced", 0) + total_synced,
            },
        }

    def _sync_folder_incremental(
        self,
        group_id: str,
        msal_client: MSALClient,
        folder_id: str,
        folder_name: str,
        last_sync_time: str,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """增量同步单个文件夹"""
        try:
            filter_str = f"receivedDateTime gt {last_sync_time}"
            all_mails = []
            skip_token = None
            batch_count = 0

            while batch_count < 20:
                response = msal_client.list_messages(
                    folder_id=folder_id,
                    top=50,
                    filter_str=filter_str,
                    orderby="receivedDateTime desc",
                    skip_token=skip_token,
                    select=[
                        "id", "subject", "from", "toRecipients", "ccRecipients",
                        "receivedDateTime", "sentDateTime", "isRead", "hasAttachments",
                        "bodyPreview", "internetMessageId", "parentFolderId",
                    ],
                )

                mails = response.get("value", [])
                if not mails:
                    break

                all_mails.extend(mails)

                next_link = response.get("@odata.nextLink")
                if next_link:
                    match = re.search(r"\$skiptoken=([^&]+)", next_link)
                    skip_token = match.group(1) if match else None
                else:
                    break

                batch_count += 1

            synced = self.save_mails_to_db(group_id, all_mails, progress_callback)
            return {"synced": synced, "fetched": len(all_mails)}

        except Exception as e:
            print(f"增量同步文件夹 {folder_name} 失败: {e}")
            return {"synced": 0, "fetched": 0}

    def sync_recent(
        self,
        group_id: str,
        msal_client: MSALClient,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """同步最近的邮件"""
        primary_account_id = self.get_primary_account_id(group_id)

        if progress_callback:
            if primary_account_id:
                progress_callback(group_id, f"[账号{primary_account_id}] 获取所有文件夹最近 {days} 天的邮件...")

        all_folders = self._get_all_folders(msal_client)
        if not all_folders:
            return {"success": False, "error": "未找到文件夹", "synced": 0}

        total_synced = 0
        total_fetched = 0
        start_date = utc_days_ago(days)

        for folder in all_folders:
            folder_id = folder["id"]
            folder_name = folder["name"]

            if folder["total"] == 0:
                continue

            if progress_callback:
                progress_callback(group_id, f"[账号{primary_account_id}] 同步文件夹: {folder_name} (最近 {days} 天)")

            result = self._sync_folder_recent(
                group_id, msal_client, folder_id, folder_name, start_date, progress_callback
            )

            total_synced += result.get("synced", 0)
            total_fetched += result.get("fetched", 0)

        return {
            "success": True,
            "synced": total_synced,
            "total_fetched": total_fetched,
            "sync_state": {
                "last_sync_time": utc_now(),
                "total_synced": total_synced,
            },
        }

    def _sync_folder_recent(
        self,
        group_id: str,
        msal_client: MSALClient,
        folder_id: str,
        folder_name: str,
        start_date: str,
        progress_callback: Optional[Callable[[str, str], None]] = None,
        max_mails: int = 500,
    ) -> Dict[str, Any]:
        """同步单个文件夹最近的邮件"""
        try:
            filter_str = f"receivedDateTime gt {start_date}"
            all_mails = []
            skip_token = None
            batch_count = 0

            while len(all_mails) < max_mails and batch_count < 20:
                response = msal_client.list_messages(
                    folder_id=folder_id,
                    top=50,
                    filter_str=filter_str,
                    orderby="receivedDateTime desc",
                    skip_token=skip_token,
                    select=[
                        "id", "subject", "from", "toRecipients", "ccRecipients",
                        "receivedDateTime", "sentDateTime", "isRead", "hasAttachments",
                        "bodyPreview", "internetMessageId", "parentFolderId",
                    ],
                )

                mails = response.get("value", [])
                if not mails:
                    break

                all_mails.extend(mails)

                next_link = response.get("@odata.nextLink")
                if next_link:
                    match = re.search(r"\$skiptoken=([^&]+)", next_link)
                    skip_token = match.group(1) if match else None
                else:
                    break

                batch_count += 1

            synced = self.save_mails_to_db(group_id, all_mails, progress_callback)
            return {"synced": synced, "fetched": len(all_mails)}

        except Exception as e:
            print(f"同步文件夹 {folder_name} 失败: {e}")
            return {"synced": 0, "fetched": 0}

    def sync_full(
        self,
        group_id: str,
        msal_client: MSALClient,
        sync_state: Dict,
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """完整同步"""
        primary_account_id = self.get_primary_account_id(group_id)

        if progress_callback:
            if primary_account_id:
                progress_callback(group_id, f"[账号{primary_account_id}] 开始完整同步所有文件夹...")

        try:
            all_folders = self._get_all_folders(msal_client)
            if not all_folders:
                return {"success": False, "error": "未找到任何文件夹", "synced": 0}

            all_folders.sort(key=lambda f: f["total"], reverse=True)

            if progress_callback:
                total_mails = sum(f["total"] for f in all_folders)
                progress_callback(group_id, f"[账号{primary_account_id}] 找到 {len(all_folders)} 个文件夹，共 {total_mails} 封邮件")

            all_synced = 0
            all_fetched = 0

            for folder in all_folders:
                folder_id = folder["id"]
                folder_name = folder["name"]

                if folder["total"] == 0:
                    continue

                if progress_callback:
                    progress_callback(group_id, f"[账号{primary_account_id}] 正在同步文件夹: {folder_name} ({folder['total']} 封)")

                result = self._sync_folder_full(
                    group_id, msal_client, folder, None, progress_callback
                )

                all_synced += result.get("synced", 0)
                all_fetched += result.get("fetched", 0)

            return {
                "success": True,
                "synced": all_synced,
                "total_fetched": all_fetched,
                "sync_state": {
                    "last_sync_time": utc_now(),
                    "total_synced": sync_state.get("total_synced", 0) + all_synced,
                },
            }

        except Exception as e:
            return {"success": False, "error": f"完整同步失败: {str(e)}", "synced": 0}

    def _sync_folder_full(
        self,
        group_id: str,
        msal_client: MSALClient,
        folder: Dict,
        skip_token: Optional[str],
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> Dict[str, Any]:
        """同步单个文件夹的所有邮件"""
        folder_id = folder["id"]
        folder_name = folder["name"]

        all_mails = []
        batch_count = 0
        total_saved = 0
        max_batches = 100

        try:
            while batch_count < max_batches:
                response = msal_client.list_messages(
                    folder_id=folder_id,
                    top=50,
                    orderby="receivedDateTime desc",
                    skip_token=skip_token,
                    select=[
                        "id", "subject", "from", "toRecipients", "ccRecipients",
                        "receivedDateTime", "sentDateTime", "isRead", "hasAttachments",
                        "bodyPreview", "internetMessageId", "parentFolderId",
                    ],
                )

                mails = response.get("value", [])
                if not mails:
                    break

                all_mails.extend(mails)

                next_link = response.get("@odata.nextLink")
                if next_link:
                    match = re.search(r"\$skiptoken=([^&]+)", next_link)
                    skip_token = match.group(1) if match else None
                else:
                    break

                batch_count += 1

                # 定期保存邮件
                if len(all_mails) >= 200:
                    saved_count = self.save_mails_to_db(group_id, all_mails, progress_callback)
                    total_saved += saved_count
                    all_mails = []

            # 保存剩余的邮件
            if all_mails:
                saved_count = self.save_mails_to_db(group_id, all_mails, progress_callback)
                total_saved += saved_count

            return {"synced": total_saved, "fetched": total_saved, "skip_token": skip_token}

        except Exception as e:
            print(f"同步文件夹 {folder_name} 失败: {e}")
            return {"synced": 0, "fetched": 0, "skip_token": skip_token}

    def save_mails_to_db(
        self,
        group_id: str,
        mails: List[Dict],
        progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> int:
        """批量保存邮件到数据库"""
        if not mails:
            return 0

        primary_account_id = self.get_primary_account_id(group_id)

        if progress_callback and primary_account_id:
            progress_callback(group_id, f"[账号{primary_account_id}] 正在保存 {len(mails)} 封邮件到数据库...")

        saved_count = 0

        mail_data_list = []
        for mail in mails:
            try:
                mail_data = self.prepare_mail_data(group_id, mail)
                mail_data_list.append(mail_data)
            except Exception as e:
                print(f"准备邮件数据失败: {e}")
                continue

        try:
            batch_size = 100
            account_record = db.execute(
                "SELECT id FROM accounts WHERE group_id = ? LIMIT 1",
                (group_id,)
            ).fetchone()
            account_id = account_record["id"] if account_record else None

            for i in range(0, len(mail_data_list), batch_size):
                batch = mail_data_list[i:i+batch_size]

                mail_values = []
                for mail_data in batch:
                    mail_values.append((
                        mail_data["group_id"],
                        account_id,
                        mail_data["msg_uid"],
                        mail_data["msg_id"],
                        mail_data["subject"],
                        mail_data["from_addr"],
                        mail_data["from_name"],
                        ",".join(mail_data["to"]) if mail_data["to"] else "",
                        mail_data["folder_id"],
                        mail_data["sent_at"],
                        mail_data["received_at"],
                        mail_data["snippet"],
                        mail_data["flags"],
                        mail_data["attachments_count"],
                        utc_now()
                    ))

                cursor = db.cursor()
                cursor.executemany("""
                    INSERT OR IGNORE INTO mail_message (
                        group_id, account_id, msg_uid, msg_id, subject, from_addr, from_name,
                        to_joined, folder, sent_at, received_at, snippet,
                        flags, attachments_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, mail_values)

                saved_count += cursor.rowcount
                db.commit()

        except Exception as e:
            print(f"批量保存邮件失败: {e}")
            db.rollback()
            return saved_count

        return saved_count

    def prepare_mail_data(self, group_id: str, mail: Dict) -> Dict:
        """准备邮件数据用于保存"""
        to_recipients = [r.get("emailAddress", {}).get("address", "") for r in mail.get("toRecipients", [])]
        cc_recipients = [r.get("emailAddress", {}).get("address", "") for r in mail.get("ccRecipients", [])]

        from_addr = ""
        from_name = ""
        if mail.get("from"):
            from_addr = mail["from"].get("emailAddress", {}).get("address", "")
            from_name = mail["from"].get("emailAddress", {}).get("name", "")

        sent_at = mail.get("sentDateTime")
        received_at = mail.get("receivedDateTime")

        mail_data = {
            "group_id": group_id,
            "msg_uid": mail.get("id", ""),
            "msg_id": mail.get("internetMessageId", ""),
            "subject": mail.get("subject", ""),
            "from_addr": from_addr,
            "from_name": from_name,
            "to": to_recipients,
            "cc": cc_recipients,
            "folder_id": mail.get("parentFolderId", ""),
            "sent_at": sent_at,
            "received_at": received_at,
            "snippet": mail.get("bodyPreview", ""),
            "flags": 0 if mail.get("isRead", False) else 1,
            "attachments_count": len(mail.get("attachments", [])),
        }
        return mail_data