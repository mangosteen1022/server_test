"""
异步同步适配器
继承 MailSyncManager，将"写入数据库"的行为替换为"推送到 Redis 队列"
"""
import json
import redis
from typing import List, Dict, Optional, Callable

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
    重写了 save_mails_to_db，将数据推送到 Redis 而不是直接写库
    """

    def save_mails_to_db(
            self,
            group_id: str,
            mails: List[Dict],
            progress_callback: Optional[Callable[[str, str], None]] = None,
    ) -> int:
        """
        [重写] 将邮件数据推送到 Redis 缓冲队列
        """
        if not mails:
            return 0

        # 1. 获取 account_id (读操作，SQLite 并发读没问题)
        # 我们仍需要 account_id 来建立关联
        with get_db() as db:
            row = db.execute("SELECT id FROM accounts WHERE group_id = ?", (group_id,)).fetchone()
            account_id = row["id"] if row else None

        if not account_id:
            return 0

        # 2. 准备数据
        items_to_push = []

        for mail in mails:
            try:
                # 复用父类的数据清洗逻辑
                mail_data = self.prepare_mail_data(group_id, mail)

                # A. 构造 mail_message 数据包
                msg_payload = {
                    "table": "mail_message",
                    "data": {
                        "group_id": group_id,
                        "account_id": account_id,
                        "msg_uid": mail_data["msg_uid"],
                        "msg_id": mail_data["msg_id"],
                        "subject": mail_data["subject"],
                        "from_addr": mail_data["from_addr"],
                        "from_name": mail_data["from_name"],
                        "to_joined": ",".join(mail_data["to"]) if mail_data["to"] else "",
                        "folder_id": mail_data["folder_id"],
                        "sent_at": mail_data["sent_at"],
                        "received_at": mail_data["received_at"],
                        "snippet": mail_data["snippet"],
                        "flags": mail_data["flags"],
                        "attachments_count": mail_data["attachments_count"],
                        "created_at": utc_now()
                    }
                }
                items_to_push.append(json.dumps(msg_payload, default=str))

            except Exception as e:
                print(f"Async prepare failed: {e}")
                continue

        # 3. 批量推送到 Redis (Pipeline)
        if items_to_push:
            try:
                pipe = redis_client.pipeline()
                for item in items_to_push:
                    pipe.lpush(RedisKeys.DB_WRITE_QUEUE, item)
                pipe.execute()

                # 触发进度回调 (为了让前端看到进度条走动)
                if progress_callback:
                    progress_callback(group_id, f"已缓冲 {len(items_to_push)} 封邮件")

                return len(items_to_push)
            except Exception as e:
                print(f"Redis push failed: {e}")
                return 0

        return 0