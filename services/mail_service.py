"""邮件业务逻辑服务 - 重构版"""

import traceback
from typing import Optional, List, Dict, Any, Tuple

from fastapi import HTTPException
from database.factory import get_db, begin_tx, commit_tx, rollback_tx
from models.mail import MailBodyIn, MailMessageCreate, MailMessageUpdate, MailSearchRequest, MailMessageBatchCreate
from utils.normalizers import normalize_list
from utils.logger import get_logger

logger = get_logger(__name__)


class MailService:
    """邮件服务"""

    def __init__(self):
        """初始化服务，不接收 db 连接"""
        pass

    def create_message(self, it: MailMessageCreate) -> Dict[str, Any]:
        """创建邮件消息"""
        to_all = normalize_list(it.to) + normalize_list(it.cc) + normalize_list(it.bcc)
        seen, seq = set(), []
        for a in to_all:
            if a not in seen:
                seen.add(a)
                seq.append(a)
        to_joined = ";".join(seq)

        labels_joined = ";".join(normalize_list(it.labels))
        attachments_count = len(it.attachments or [])

        try:
            with get_db() as db:
                begin_tx(db)

                cursor = db.execute(
                    """
                    INSERT INTO mail_message(
                        group_id, account_id, msg_uid, msg_id, subject, from_addr, to_joined,
                        folder_id, labels_joined, sent_at, received_at, size_bytes,
                        attachments_count, flags, snippet, created_at, updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
                """,
                    (
                        it.group_id,
                        it.account_id,
                        it.msg_uid,
                        it.msg_id,
                        it.subject or "",
                        it.from_addr,
                        to_joined,
                        it.folder_id,
                        labels_joined,
                        it.sent_at,
                        it.received_at,
                        it.size_bytes,
                        attachments_count,
                        ";".join(it.flags or []),
                        it.snippet or ""
                    )
                )

                commit_tx(db)
                return {"id": cursor.lastrowid}

        except Exception as e:
            logger.error(f"Failed to create message: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def get_message(self, account_id: int, message_id: int) -> Optional[Dict]:
        """获取邮件详情"""
        return self.fetch_one(
            "SELECT * FROM mail_message WHERE account_id = ? AND id = ?",
            (account_id, message_id)
        )

    def list_messages(self, account_id: int, params: Dict = None) -> Dict[str, Any]:
        """获取邮件列表"""
        query = "SELECT * FROM mail_message WHERE account_id = ?"
        query_params = [account_id]

        if params:
            # 构建查询条件
            conditions = []
            if params.get("folder_id"):
                conditions.append("folder_id = ?")
                query_params.append(params["folder_id"])
            if params.get("search"):
                conditions.append("(subject LIKE ? OR from_addr LIKE ? OR to_joined LIKE ?)")
                search_term = f"%{params['search']}%"
                query_params.extend([search_term, search_term, search_term])
            if params.get("has_attachments") is True:
                conditions.append("attachments_count > 0")
            if params.get("is_unread") is True:
                conditions.append("flags NOT LIKE '%Read%'")
            if params.get("is_flagged") is True:
                conditions.append("flags LIKE '%Flagged%'")

            if conditions:
                query += " AND " + " AND ".join(conditions)

        query += " ORDER BY received_at DESC"

        # 使用分页
        page = params.get("page", 1)
        size = params.get("size", 50)

        return self.paginate(query, page, size, tuple(query_params))

    def update_message(self, account_id: int, message_id: int, data: MailMessageUpdate) -> bool:
        """更新邮件"""
        update_fields = []
        update_values = []

        if data.flags is not None:
            update_fields.append("flags = ?")
            update_values.append(";".join(data.flags))

        if data.folder_id is not None:
            update_fields.append("folder_id = ?")
            update_values.append(data.folder_id)

        if not update_fields:
            return False

        update_values.extend([account_id, message_id])

        try:
            with get_db() as db:
                begin_tx(db)
                db.execute(
                    f"UPDATE mail_message SET {', '.join(update_fields)} WHERE account_id = ? AND id = ?",
                    tuple(update_values)
                )
                commit_tx(db)
                return True
        except Exception as e:
            logger.error(f"Failed to update message {message_id}: {str(e)}")
            return False

    def delete_message(self, account_id: int, message_id: int) -> bool:
        """删除邮件"""
        try:
            with get_db() as db:
                begin_tx(db)
                cursor = db.execute(
                    "DELETE FROM mail_message WHERE account_id = ? AND id = ?",
                    (account_id, message_id)
                )
                commit_tx(db)
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete message {message_id}: {str(e)}")
            return False

    def batch_create_messages(self, messages: List[MailMessageBatchCreate]) -> Dict[str, Any]:
        """批量创建邮件"""
        success_count = 0
        errors = []

        for idx, msg in enumerate(messages):
            try:
                # 转换为 MailMessageCreate
                create_data = MailMessageCreate(
                    group_id=msg.group_id,
                    account_id=msg.account_id,
                    msg_uid=msg.msg_uid,
                    msg_id=msg.msg_id,
                    subject=msg.subject,
                    from_addr=msg.from_addr,
                    to=msg.to,
                    cc=msg.cc,
                    bcc=msg.bcc,
                    folder_id=msg.folder_id,
                    labels=msg.labels,
                    flags=msg.flags,
                    snippet=msg.snippet
                )

                self.create_message(create_data)
                success_count += 1
            except Exception as e:
                errors.append({"index": idx, "error": str(e)})

        return {
            "total": len(messages),
            "success": success_count,
            "errors": errors
        }

    def search_messages(self, account_id: int, search: MailSearchRequest) -> Dict[str, Any]:
        """搜索邮件"""
        query = "SELECT * FROM mail_message WHERE account_id = ?"
        params = [account_id]

        # 构建搜索条件
        conditions = []

        if search.query:
            conditions.append(
                "(subject LIKE ? OR from_addr LIKE ? OR to_joined LIKE ? OR body LIKE ?)"
            )
            search_term = f"%{search.query}%"
            params.extend([search_term, search_term, search_term, search_term])

        if search.folder_id:
            conditions.append("folder_id = ?")
            params.append(search.folder_id)

        if search.from_addr:
            conditions.append("from_addr LIKE ?")
            params.append(f"%{search.from_addr}%")

        if search.has_attachments is not None:
            if search.has_attachments:
                conditions.append("attachments_count > 0")
            else:
                conditions.append("attachments_count = 0")

        if search.is_unread is not None:
            if search.is_unread:
                conditions.append("flags NOT LIKE '%Read%'")
            else:
                conditions.append("flags LIKE '%Read%'")

        if search.is_flagged is not None:
            if search.is_flagged:
                conditions.append("flags LIKE '%Flagged%'")
            else:
                conditions.append("flags NOT LIKE '%Flagged%'")

        if search.date_from:
            conditions.append("received_at >= ?")
            params.append(search.date_from)

        if search.date_to:
            conditions.append("received_at <= ?")
            params.append(search.date_to)

        if conditions:
            query += " AND " + " AND ".join(conditions)

        query += " ORDER BY received_at DESC"

        return self.paginate(query, search.page or 1, search.size or 50, tuple(params))

    def get_message_count_by_folder(self, account_id: int) -> Dict[str, int]:
        """获取各文件夹的邮件数量"""
        query = """
            SELECT folder_id, COUNT(*) as count
            FROM mail_message
            WHERE account_id = ?
            GROUP BY folder_id
        """

        with get_db() as db:
            rows = db.execute(query, (account_id,)).fetchall()
            return {row["folder_id"]: row["count"] for row in rows}

    def get_unread_count(self, account_id: int) -> int:
        """获取未读邮件数量"""
        return self.fetch_value(
            "SELECT COUNT(*) FROM mail_message WHERE account_id = ? AND flags NOT LIKE '%Read%'",
            (account_id,)
        ) or 0

    def mark_as_read(self, account_id: int, message_ids: List[int]) -> int:
        """标记邮件为已读"""
        if not message_ids:
            return 0

        placeholders = ",".join(["?"] * len(message_ids))
        try:
            with get_db() as db:
                begin_tx(db)
                # 获取当前flags
                rows = db.execute(
                    f"SELECT id, flags FROM mail_message WHERE account_id = ? AND id IN ({placeholders})",
                    [account_id] + message_ids
                ).fetchall()

                # 更新flags
                for row in rows:
                    flags = row["flags"].split(";") if row["flags"] else []
                    if "Read" not in flags:
                        flags.append("Read")
                        db.execute(
                            "UPDATE mail_message SET flags = ? WHERE id = ?",
                            (";".join(flags), row["id"])
                        )

                commit_tx(db)
                return len(rows)
        except Exception as e:
            logger.error(f"Failed to mark messages as read: {str(e)}")
            return 0

    # ==================== 私有辅助方法 ====================

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

    def paginate(self, query: str, page: int, size: int, params: Tuple = ()) -> Dict[str, Any]:
        """分页查询"""
        offset = (page - 1) * size

        # 获取总数
        total_query = f"SELECT COUNT(*) FROM ({query}) as subq"
        total = self.fetch_value(total_query, params) or 0

        # 获取分页数据
        paginated_query = f"{query} LIMIT ? OFFSET ?"
        items = self.fetch_all(paginated_query, params + (size, offset))

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size
        }

    def get_detail(self, message_id: int) -> Optional[Dict]:
        """获取邮件详情"""
        with get_db() as db:
            # 获取邮件基本信息
            mail = db.execute(
                "SELECT * FROM mail_message WHERE id = ?",
                (message_id,)
            ).fetchone()

            if not mail:
                return None

            # 获取邮件正文
            body = db.execute(
                "SELECT * FROM mail_body WHERE message_id = ?",
                (message_id,)
            ).fetchone()

            # 获取附件列表
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
        with get_db() as db:
            mail = db.execute(
                "SELECT id, subject, from_addr, to_joined, snippet, received_at, flags, folder_id FROM mail_message WHERE id = ?",
                (message_id,)
            ).fetchone()

            if not mail:
                return None

            return dict(mail)

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

    def add_attachment(self, message_id: int, storage_url: str) -> Dict:
        """添加邮件附件"""
        try:
            with get_db() as db:
                begin_tx(db)

                cursor = db.execute("""
                    INSERT INTO mail_attachment (message_id, storage_url, created_at)
                    VALUES (?, ?, datetime('now'))
                """, (message_id, storage_url))

                commit_tx(db)
                return {"id": cursor.lastrowid}
        except Exception as e:
            logger.error(f"Failed to add attachment to message {message_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def list_attachments(self, message_id: int) -> List[Dict]:
        """列出邮件附件"""
        with get_db() as db:
            attachments = db.execute(
                "SELECT * FROM mail_attachment WHERE message_id = ? ORDER BY id",
                (message_id,)
            ).fetchall()

            return [dict(a) for a in attachments]

    def delete_attachment(self, message_id: int, attach_id: int) -> bool:
        """删除邮件附件"""
        try:
            with get_db() as db:
                begin_tx(db)

                cursor = db.execute(
                    "DELETE FROM mail_attachment WHERE message_id = ? AND id = ?",
                    (message_id, attach_id)
                )

                commit_tx(db)
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete attachment {attach_id}: {str(e)}")
            return False

    def list_account_mails(self, account_id: int, q: Optional[str] = None,
                          folder: Optional[str] = None, page: int = 1, size: int = 50) -> Dict:
        """列出账号邮件"""
        params = {
            "search": q,
            "folder_id": folder
        }
        return self.list_messages(account_id, params)

    def search_mails(self, req: MailSearchRequest) -> Dict:
        """批量搜索邮件"""
        # 临时实现 - 假设只搜索单个账号
        if req.account_ids:
            account_id = req.account_ids[0]  # 简化处理
            return self.search_messages(account_id, req)
        else:
            # 如果没有指定账号，返回空结果
            return {
                "items": [],
                "total": 0,
                "page": req.page or 1,
                "size": req.size or 50,
                "pages": 0
            }

    def batch_create_messages_optimized(self, batch_data: MailMessageBatchCreate) -> Dict:
        """优化版本的批量创建邮件"""
        # 简化实现，直接调用普通版本
        return self.batch_create_messages(batch_data.mails)

    def update_message(self, message_id: int, body: MailMessageUpdate) -> Dict:
        """更新邮件消息"""
        # 需要先获取account_id
        with get_db() as db:
            mail = db.execute(
                "SELECT account_id FROM mail_message WHERE id = ?",
                (message_id,)
            ).fetchone()

            if not mail:
                raise HTTPException(404, "邮件不存在")

        # 调用内部方法
        success = self._update_message_internal(mail["account_id"], message_id, body)

        if not success:
            raise HTTPException(500, "更新失败")

        return {"success": True}

    def delete_message(self, message_id: int) -> Dict:
        """删除邮件消息"""
        # 需要先获取account_id
        with get_db() as db:
            mail = db.execute(
                "SELECT account_id FROM mail_message WHERE id = ?",
                (message_id,)
            ).fetchone()

            if not mail:
                raise HTTPException(404, "邮件不存在")

        # 调用内部方法
        success = self._delete_message_internal(mail["account_id"], message_id)

        if not success:
            raise HTTPException(500, "删除失败")

        return {"success": True}

    def _update_message_internal(self, account_id: int, message_id: int, data: MailMessageUpdate) -> bool:
        """内部更新邮件方法"""
        update_fields = []
        update_values = []

        if data.flags is not None:
            update_fields.append("flags = ?")
            update_values.append(";".join(data.flags))

        if data.folder_id is not None:
            update_fields.append("folder_id = ?")
            update_values.append(data.folder_id)

        if not update_fields:
            return False

        update_values.extend([account_id, message_id])

        try:
            with get_db() as db:
                begin_tx(db)
                db.execute(
                    f"UPDATE mail_message SET {', '.join(update_fields)} WHERE account_id = ? AND id = ?",
                    tuple(update_values)
                )
                commit_tx(db)
                return True
        except Exception as e:
            logger.error(f"Failed to update message {message_id}: {str(e)}")
            return False

    def _delete_message_internal(self, account_id: int, message_id: int) -> bool:
        """内部删除邮件方法"""
        try:
            with get_db() as db:
                begin_tx(db)
                cursor = db.execute(
                    "DELETE FROM mail_message WHERE account_id = ? AND id = ?",
                    (account_id, message_id)
                )
                commit_tx(db)
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete message {message_id}: {str(e)}")
            return False