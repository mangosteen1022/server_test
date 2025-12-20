"""邮件业务逻辑服务"""
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any, Tuple, Callable

import redis
import requests

import settings
from auth.msal_client import MSALClient
from database.factory import get_db, begin_tx, commit_tx
from models.mail import MailBodyIn, MailSearchRequest
from utils.logger import get_logger

logger = get_logger(__name__)


class MailService:
    """邮件服务"""

    def get_message(self, group_id: str, message_id: int) -> Optional[Dict]:
        """获取邮件详情 (按 Group 查询)"""
        return self.fetch_one(
            "SELECT * FROM mail_message WHERE group_id = ? AND id = ?",
            (group_id, message_id)
        )

    def list_messages(self, group_id: str, params: Dict = None, current_user: Dict = None) -> Dict[str, Any]:
        """
        获取邮件列表
        [重构]：现在它只是 search_group_mails 的一个轻量级封装
        """
        if params is None:
            params = {}

        # 为了复用 _execute_mail_search 的纯净逻辑，我们在这里先鉴权
        if current_user and current_user["role"] != "admin":
            if not self._has_group_permission(group_id, current_user["id"]):
                return {
                    "items": [], "total": 0, "page": params.get("page", 1), "size": params.get("size", 50), "pages": 0
                }

        # 注意：这里做参数映射
        search_req = MailSearchRequest(
            query=params.get("search"),  # 对应 q 参数
            folder_id=params.get("folder_id"),
            has_attachments=params.get("has_attachments"),
            is_unread=params.get("is_unread"),
            is_flagged=params.get("is_flagged"),
            page=params.get("page", 1),
            size=params.get("size", 50)
        )

        base_conditions = ["group_id = ?"]
        base_params = [group_id]

        return self._execute_mail_search(base_conditions, base_params, search_req)

    def delete_message(self, group_id: str, message_id: int) -> bool:
        """删除邮件 (按 Group 查询)"""
        try:
            with get_db() as db:
                begin_tx(db)
                cursor = db.execute(
                    "DELETE FROM mail_message WHERE group_id = ? AND id = ?",
                    (group_id, message_id)
                )
                commit_tx(db)
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete message {message_id}: {str(e)}")
            return False

    def batch_delete_messages(self, group_id: str, message_ids: List[int]) -> int:
        """批量删除邮件"""
        if not message_ids:
            return 0

        # 安全性：必须同时校验 group_id，防止跨组误删
        placeholders = ",".join(["?"] * len(message_ids))
        query = f"DELETE FROM mail_message WHERE group_id = ? AND id IN ({placeholders})"

        try:
            with get_db() as db:
                begin_tx(db)
                cursor = db.execute(query, [group_id] + message_ids)
                commit_tx(db)
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Failed to batch delete messages: {str(e)}")
            return 0

    def batch_update_flags(self, group_id: str, message_ids: List[int], action: str, flag: str) -> int:
        """
        批量更新邮件标志位
        :param group_id: 组ID
        :param message_ids: 邮件ID列表
        :param action: 'add' (添加) 或 'remove' (移除)
        :param flag: 标志位名称 (如 'Read', 'Flagged')
        :return: 成功更新的记录数
        """
        if not message_ids:
            return 0

        # 校验 action 合法性
        if action not in ("add", "remove"):
            return 0

        placeholders = ",".join(["?"] * len(message_ids))

        try:
            with get_db() as db:
                begin_tx(db)

                # 1. 查出当前所有选中邮件的 flags
                rows = db.execute(
                    f"SELECT id, flags FROM mail_message WHERE group_id = ? AND id IN ({placeholders})",
                    [group_id] + message_ids
                ).fetchall()

                updated_count = 0

                for row in rows:
                    # 解析当前 flags (数据库存的是分号分隔字符串 "Read;Flagged")
                    # 使用 set 自动去重且查找快
                    current_flags = set(row["flags"].split(";") if row["flags"] else [])

                    original_len = len(current_flags)

                    # 2. 根据 action 修改集合
                    if action == "add":
                        current_flags.add(flag)
                    elif action == "remove":
                        if flag in current_flags:
                            current_flags.remove(flag)

                    # 3. 只有当 flags 真正发生变化时才执行 SQL 更新
                    if len(current_flags) != original_len:
                        new_flags_str = ";".join(sorted(current_flags))  # 排序保证存储顺序一致
                        db.execute(
                            "UPDATE mail_message SET flags = ? WHERE id = ?",
                            (new_flags_str, row["id"])
                        )
                        updated_count += 1

                commit_tx(db)
                return updated_count

        except Exception as e:
            logger.error(f"Failed to batch update flags: {str(e)}")
            return 0

    def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Dict]:
        """执行查询并返回单条记录"""
        with get_db() as db:
            cursor = db.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, query: str, params: Tuple = ()) -> List[Dict]:
        """执行查询并返回所有记录"""
        with get_db() as db:
            cursor = db.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def fetch_value(self, query: str, params: Tuple = ()) -> Any:
        """执行查询并返回单个值"""
        with get_db() as db:
            cursor = db.execute(query, params)
            row = cursor.fetchone()
            return row[0] if row else None

    def get_detail(self, message_id: int) -> Optional[Dict]:
        """获取邮件详情"""
        with get_db() as db:
            mail = db.execute(
                "SELECT * FROM mail_message WHERE id = ?",
                (message_id,)
            ).fetchone()

            if not mail:
                return None

            body = db.execute(
                "SELECT * FROM mail_body WHERE message_id = ?",
                (message_id,)
            ).fetchone()

            attachments = db.execute(
                "SELECT * FROM mail_attachment WHERE message_id = ? ORDER BY id",
                (message_id,)
            ).fetchall()

            result = dict(mail)
            result["body"] = dict(body) if body else None
            result["attachments"] = [dict(a) for a in attachments]

            return result

    def get_preview(self, message_id: int) -> Optional[Dict]:
        """获取邮件预览（用于右侧显示）"""
        return self.fetch_one(
            "SELECT id, subject, from_addr, to_joined, snippet, received_at, flags, folder_id FROM mail_message WHERE id = ?",
            (message_id,)
        )

    def update_body(self, message_id: int, body_data: MailBodyIn) -> bool:
        """更新或插入邮件正文"""
        try:
            with get_db() as db:
                begin_tx(db)

                # 更新或插入
                db.execute("""
                    INSERT OR REPLACE INTO mail_body (message_id, headers, body_plain, body_html)
                    VALUES (?, ?, ?, ?)
                """, (
                    message_id,
                    body_data.headers,
                    body_data.body_plain,
                    body_data.body_html
                ))

                commit_tx(db)
                return True
        except Exception as e:
            logger.error(f"Failed to update body for message {message_id}: {str(e)}")
            return False

    def list_attachments(self, message_id: int) -> List[Dict]:
        """列出邮件附件"""
        with get_db() as db:
            attachments = db.execute(
                "SELECT * FROM mail_attachment WHERE message_id = ? ORDER BY id",
                (message_id,)
            ).fetchall()

            return [dict(a) for a in attachments]

    def _has_group_permission(self, group_id: str, user_id: int) -> bool:
        """
        [高效鉴权] 检查用户是否拥有该组下的任意一个账号
        SQL 复杂度: O(1) - 仅查询关系表
        """
        query = """
                SELECT 1
                FROM accounts a
                         JOIN project_assignments pa ON a.id = pa.account_id
                WHERE a.group_id = ? \
                  AND pa.user_id = ?
                LIMIT 1 \
                """
        # 只要查到一条记录，就说明有权访问该组
        return self.fetch_value(query, (group_id, user_id)) is not None

    def search_group_mails(self, group_id: str, search: MailSearchRequest, current_user: Dict) -> Dict[str, Any]:
        """
        搜索指定组的邮件
        """
        # 1. 权限检查
        if current_user["role"] != "admin":
            if not self._has_group_permission(group_id, current_user["id"]):
                return {
                    "items": [], "total": 0, "page": search.page, "size": search.size, "pages": 0
                }

        # 2. 执行搜索
        base_conditions = ["group_id = ?"]
        base_params = [group_id]
        return self._execute_mail_search(base_conditions, base_params, search)

    def search_all_mails(
            self, search: MailSearchRequest, current_user: Dict, project_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        全量搜索邮件 (带项目维度和权限控制)

        逻辑矩阵:
        1. 管理员 + 指定项目: 搜索该项目分配出去的所有账号的邮件 (不限用户)
        2. 管理员 + 无项目  : 搜索全库邮件
        3. 普通用户 + 指定项目: 搜索分配给该用户的、且属于该项目的账号的邮件
        4. 普通用户 + 无项目  : 搜索分配给该用户的所有账号的邮件
        """
        base_conditions = []
        base_params = []

        if current_user["role"] == "admin":
            if project_id:
                # 1. 管理员 + 指定项目 -> 该项目下的所有账号 (通过 project_assignments 关联)
                base_conditions.append("""
                    account_id IN (
                        SELECT account_id 
                        FROM project_assignments 
                        WHERE project_id = ?
                    )
                """)
                base_params.append(project_id)
            else:
                # 2. 管理员 + 无项目 -> 全量搜索 (无额外 WHERE 条件)
                pass
        else:
            # 普通用户
            if project_id:
                # 3. 普通用户 + 指定项目 -> 自己在该项目下的账号
                base_conditions.append("""
                    account_id IN (
                        SELECT account_id 
                        FROM project_assignments 
                        WHERE user_id = ? AND project_id = ?
                    )
                """)
                base_params.extend([current_user["id"], project_id])
            else:
                # 4. 普通用户 + 无项目 -> 自己所有的账号
                base_conditions.append("""
                    account_id IN (
                        SELECT account_id 
                        FROM project_assignments 
                        WHERE user_id = ?
                    )
                """)
                base_params.append(current_user["id"])

        return self._execute_mail_search(base_conditions, base_params, search)

    def _execute_mail_search(
            self, conditions: List[str], params: List[Any], search: MailSearchRequest
    ) -> Dict[str, Any]:
        """
        内部通用搜索执行器
        """
        # 1. 动态构建搜索条件
        if search.query:
            term = f"%{search.query}%"
            conditions.append("(subject LIKE ? OR from_addr LIKE ? OR to_joined LIKE ?)")
            params.extend([term, term, term])

        if getattr(search, 'subject', None):
            conditions.append("subject LIKE ?")
            params.append(f"%{search.subject}%")

        if getattr(search, 'from_addr', None):
            conditions.append("from_addr LIKE ?")
            params.append(f"%{search.from_addr}%")

        if getattr(search, 'to_addr', None):
            conditions.append("to_joined LIKE ?")
            params.append(f"%{search.to_addr}%")

        if search.folder_id:
            conditions.append("folder_id = ?")
            params.append(search.folder_id)

        if search.has_attachments is not None:
            op = ">" if search.has_attachments else "="
            conditions.append(f"has_attachments {op} 0")

        if search.is_unread is not None:
            if search.is_unread:
                conditions.append("flags NOT LIKE '%Read%'")
            else:
                conditions.append("flags LIKE '%Read%'")

        if search.date_from:
            conditions.append("received_at >= ?")
            params.append(search.date_from)

        if search.date_to:
            conditions.append("received_at <= ?")
            params.append(search.date_to)

        # 2. 组合 SQL
        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)

        # 3. 计算总数
        count_query = f"SELECT COUNT(*) FROM mail_message {where_clause}"
        total = self.fetch_value(count_query, tuple(params)) or 0

        # 4. 执行查询
        select_fields = """
            id, group_id, account_id, subject, from_addr, from_name, 
            to_joined, folder_id, sent_at, received_at, size_bytes, 
            has_attachments, flags, snippet
        """

        page = search.page or 1
        size = search.size or 50
        offset = (page - 1) * size

        list_query = f"""
            SELECT {select_fields} 
            FROM mail_message 
            {where_clause} 
            ORDER BY received_at DESC 
            LIMIT ? OFFSET ?
        """

        full_params = params + [size, offset]
        items = self.fetch_all(list_query, tuple(full_params))

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size
        }

    def batch_download_content(self, message_ids: List[int], max_workers: int = 10,
                               progress_callback: Optional[Callable[[int, int], None]] = None
                               ) -> Dict[str, Any]:
        """
        批量下载邮件内容 + 附件元数据
        """
        if not message_ids:
            return {"success": True, "total": 0, "downloaded": 0, "skipped": 0, "errors": []}

        # --- 1. 准备元数据 & 智能过滤 ---
        tasks_metadata = []
        placeholders = ",".join(["?"] * len(message_ids))

        with get_db() as db:
            # 联查: 邮件ID -> msg_uid -> token_uuid
            query = f"""SELECT 
                            m.id as message_id, 
                            m.msg_uid, 
                            m.group_id
                        FROM mail_message m
                        LEFT JOIN mail_body b ON m.id = b.message_id
                        WHERE m.id IN ({placeholders})
                          AND b.message_id IS NULL
                        """
            rows = db.execute(query, message_ids).fetchall()
            tasks_metadata = [dict(row) for row in rows]

        total_requested = len(message_ids) # 总数量
        skipped_count = total_requested - len(tasks_metadata)  # 已经下载的邮件数量,跳过

        if not tasks_metadata:
            if progress_callback:
                progress_callback(total_requested, total_requested) # 全部下载完成
            return {
                "success": True,
                "total_requested": total_requested,
                "downloaded": 0,
                "skipped": skipped_count,
                "message": "所有选中的邮件均已下载",
                "errors": []
            }

        # --- 2. 预取 Token ---
        valid_tokens = {}
        auth_errors = {}

        for task in tasks_metadata:
            gid = task["group_id"]
            message_id = task['message_id']
            if gid in valid_tokens:
                valid_tokens[gid]["tasks"].append(task)
                continue
            if gid in auth_errors:
                auth_errors[gid].append(message_id)
                continue
            try:
                msal_client = MSALClient(
                    client_id=settings.MSAL_CLIENT_ID,
                    authority=settings.MSAL_AUTHORITY,
                    scopes=settings.MSAL_SCOPES,
                    group_id=gid
                )
                token = msal_client.get_access_token()
                if token:
                    valid_tokens[gid] = {"token":token,"tasks":[task]}
                else:
                    auth_errors[gid] = [message_id]
            except Exception as e:
                logger.error(f"Token fetch failed for {gid}: {e}")
                auth_errors[gid] = [message_id]

        # --- 3. 定义轻量级下载任务 (包含附件元数据) ---
        def _lightweight_download(meta, access_token):
            try:
                url = f"https://graph.microsoft.com/v1.0/me/messages/{meta['msg_uid']}"
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                params = {
                    "$select": "internetMessageHeaders,body,subject",
                    "$expand": "attachments($select=id,name,contentType,size,isInline,contentId)"
                }
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code != 200:
                    return {"error": f"Msg {meta['message_id']} HTTP {resp.status_code}"}
                data = resp.json()
                # 解析正文
                headers_list = data.get("internetMessageHeaders", [])
                headers_str = "\n".join([f"{h.get('name', '')}: {h.get('value', '')}" for h in headers_list])
                body_obj = data.get("body", {})
                body_html = body_obj.get("content", "") if body_obj.get("contentType") == "html" else ""
                body_plain = body_obj.get("content", "") if body_obj.get("contentType") == "text" else ""

                attachments_data = []
                if data.get("attachments"):
                    for att in data["attachments"]:
                        if not att.get("id"):
                            continue
                        attachments_data.append({
                            "message_id": meta["message_id"],  # 关联本地邮件ID
                            "attachment_id": att.get("id"),  # Graph API 的附件ID
                            "filename": att.get("name"),
                            "content_type": att.get("contentType"),
                            "size": att.get("size"),
                            "is_inline": 1 if att.get("isInline") else 0,
                            "content_id": att.get("contentId"),
                            "download_status": "PENDING"
                        })
                return {
                    "message_id": meta["message_id"],
                    "headers": headers_str,
                    "body_html": body_html,
                    "body_plain": body_plain,
                    "attachments_data":attachments_data
                }
            except requests.exceptions.Timeout:
                return {"message_id": meta['message_id'], "error": "Request timeout"}
            except requests.exceptions.RequestException as e:
                return {"message_id": meta['message_id'], "error": f"Request failed: {e}"}
            except Exception as e:
                logger.exception(f"Download failed for message {meta['message_id']}")
                return {"message_id": meta['message_id'], "error": str(e)}

        # --- 4. 并发执行 ---
        success_results = []
        download_errors = []
        completed_count = skipped_count + sum(len(v) for v in auth_errors.values()) # 排除掉失败后的起始数
        progress_callback(completed_count, total_requested)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for val in list(valid_tokens.values()):
                token,tasks = val['token'],val['tasks']
                for task in tasks:
                    futures.append(executor.submit(_lightweight_download, task, token))

            for future in as_completed(futures):
                res = future.result()
                if "error" in res:
                    download_errors.append(res["error"])
                else:
                    success_results.append(res)
                completed_count += 1
                if progress_callback:
                    try:
                        progress_callback(completed_count, total_requested)
                    except Exception:
                        pass  # 忽略回调错误

        # --- 5. 批量写入 DB (Body + Attachments) ---
        if success_results:
            try:
                redis_client = redis.from_url(settings.REDIS_URL)
                pipe = redis_client.pipeline()
                for item in success_results:
                    # 构造写入任务
                    payload = {
                        "table": "mail_body",
                        "data": {
                            "message_id": item["message_id"],
                            "headers": item["headers"],
                            "body_plain": item["body_plain"],
                            "body_html": item["body_html"],
                        }
                    }
                    pipe.lpush("sys:db_write_queue", json.dumps(payload, default=str))
                    if item.get("attachments_data"):
                        for atta in item.get("attachments_data"):
                            payload = {
                                "table": "mail_attachment",
                                "data": atta
                            }
                            pipe.lpush("sys:db_write_queue", json.dumps(payload, default=str))

                pipe.execute()
            except Exception as e:
                logger.error(f"Batch save failed: {e}")
                return {"success": False, "message": f"Save failed: {str(e)}"}

        return {
            "success": True,
            "total_requested": total_requested,
            "skipped": skipped_count,
            "downloaded": len(success_results),
            "download_errors": download_errors,
            "auth_errors": auth_errors
        }
