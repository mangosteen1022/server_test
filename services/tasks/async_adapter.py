"""
异步同步适配器
文件路径: services/tasks/async_adapter.py
功能: 继承 MailSyncManager，重写 save_mails_to_db，将数据推送到 Redis 缓冲队列
"""
import json
import redis
from typing import List, Dict, Optional, Callable

# 引入原有的同步管理器
from services.mail_sync import MailSyncManager
from utils.time_utils import utc_now
from celery_app import RedisKeys
import settings
from database.factory import get_db

# 连接 Redis
redis_client = redis.from_url(settings.REDIS_URL)

class AsyncMailSyncManager(MailSyncManager):
    """
    异步版本的邮件同步管理器
    覆盖了 save_mails_to_db 方法，避免 SQLite 写入锁
    """

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

        # 1. 获取 account_id (用于建立外键关联)
        account_id = None
        try:
            with get_db() as db:
                row = db.execute("SELECT id FROM accounts WHERE group_id = ? LIMIT 1", (group_id,)).fetchone()
                if row:
                    account_id = row["id"]
        except Exception as e:
            print(f"Error getting account_id for {group_id}: {e}")
            return 0

        if not account_id:
            return 0

        # 2. 准备数据包
        items_to_push = []

        for mail in mails:
            try:
                # --- Flags 处理 ---
                # 逻辑: isRead=True -> 'Read', False -> 'UNREAD'
                # 同时保留 Flagged 状态
                flags_parts = []
                if mail.get("isRead"):
                    flags_parts.append("Read")

                if mail.get("flag", {}).get("flagStatus") == "flagged":
                    flags_parts.append("Flagged")

                flags_str = ";".join(flags_parts) if flags_parts else "UNREAD"

                has_attachments = 1 if mail.get("hasAttachments") else 0
                to_recipients = [r.get("emailAddress", {}).get("address", "") for r in mail.get("toRecipients", [])]
                to_joined = ",".join(filter(None, to_recipients))

                msg_payload = {
                    "table": "mail_message",
                    "data": {
                        "group_id": group_id,
                        "account_id": account_id,

                        # ID 信息
                        "msg_uid": mail.get("id"),          # Graph API Message ID
                        "msg_id": mail.get("internetMessageId"),

                        # 邮件内容元数据
                        "subject": mail.get("subject", ""),
                        "from_addr": mail.get("from", {}).get("emailAddress", {}).get("address", ""),
                        "from_name": mail.get("from", {}).get("emailAddress", {}).get("name", ""),
                        "to_joined": to_joined,
                        "snippet": mail.get("bodyPreview", ""),

                        # 文件夹关联 (只存 folder_id)
                        "folder_id": mail.get("parentFolderId"),

                        # 时间
                        "sent_at": mail.get("sentDateTime"),
                        "received_at": mail.get("receivedDateTime"),

                        # 属性
                        "size_bytes": mail.get("size", 0),
                        "has_attachments": has_attachments, # 0 或 1
                        "flags": flags_str,                 # 'Read;Flagged' 或 'UNREAD'

                        # 记录时间
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