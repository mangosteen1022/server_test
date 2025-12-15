"""
Celery Worker 任务定义
"""
import settings
import traceback
from celery import shared_task
from celery.utils.log import get_task_logger

from auth.msal_client import MSALClient
from services.tasks.async_adapter import AsyncMailSyncManager
from services.tasks.utils import user_concurrency_guard, update_task_status
from services.auth_service import AuthService
from database.factory import get_db, begin_tx, commit_tx
from utils.logger import get_logger

# 使用 Celery 的 Logger
celery_logger = get_task_logger(__name__)
sys_logger = get_logger(__name__)


def _get_cached_token_uuid(group_id: str):
    """直接从数据库获取缓存 UUID"""
    try:
        with get_db() as db:
            row = db.execute(
                "SELECT uuid FROM account_token_cache WHERE group_id=?",
                (group_id,)
            ).fetchone()
            return row["uuid"] if row else None
    except Exception as e:
        celery_logger.error(f"DB error getting token for {group_id}: {e}")
        return None

def _create_msal_client(token_uuid: str = None):
    """直接创建 MSAL 客户端"""
    return MSALClient(
        client_id=settings.MSAL_CLIENT_ID,
        authority=settings.MSAL_AUTHORITY,
        scopes=settings.MSAL_SCOPES,
        token_uuid=token_uuid,
        default_port=settings.MSAL_REDIRECT_PORT
    )
# ================= 邮件同步任务 =================

@shared_task(bind=True, name="tasks.sync_group")
def sync_group_task(self, group_id: str, user_id: int, role: str, strategy: str = "auto"):
    """同步任务"""
    TASK_TYPE = "sync"
    update_task_status(user_id, group_id, TASK_TYPE, "RUNNING", "初始化同步...", ttl=3600)

    with user_concurrency_guard(self, user_id, role):
        try:
            # 回调闭包
            def progress_callback(gid, msg):
                update_task_status(user_id, gid, TASK_TYPE, "RUNNING", msg, ttl=3600)

            token_uuid = _get_cached_token_uuid(group_id)
            if not token_uuid:
                update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", "未登录", ttl=60)
                return

            msal_client = _create_msal_client(token_uuid)
            manager = AsyncMailSyncManager()

            result = manager.sync_group_mails(
                group_id=group_id,
                msal_client=msal_client,
                strategy=strategy,
                progress_callback=progress_callback
            )

            status = "SUCCESS" if result.get("success") else "FAILURE"
            msg = result.get("message", "同步完成")
            if result.get("error"): msg = f"错误: {result['error']}"

            update_task_status(user_id, group_id, TASK_TYPE, status, msg, ttl=60)

        except Exception as e:
            celery_logger.error(f"Sync error: {e}")
            update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", str(e), ttl=60)


# ================= 登录任务 =================

@shared_task(bind=True, name="tasks.login_group")
def login_group_task(self, group_id: str, user_id: int, role: str, force_relogin: bool = False):
    """
    异步登录任务
    注意：登录涉及密码修改和Token更新，这部分数据至关重要，
    因此我们在 Worker 中直接写入数据库，不走 Redis 队列。
    """
    TASK_TYPE = "login"
    update_task_status(user_id, group_id, TASK_TYPE, "RUNNING", "正在登录...", ttl=3600)
    with user_concurrency_guard(self, user_id, role):
        self.update_state(state='PROGRESS', meta={'message': '准备登录...'})

        try:
            # 1. 准备账号数据
            with get_db() as db:
                accounts = db.execute(
                    "SELECT id, email, password FROM accounts WHERE group_id = ?",
                    (group_id,)
                ).fetchall()

                # 获取辅助信息 (取第一个)
                rec_email_row = db.execute(
                    "SELECT email FROM account_recovery_email WHERE group_id = ? LIMIT 1",
                    (group_id,)
                ).fetchone()

                rec_phone_row = db.execute(
                    "SELECT phone FROM account_recovery_phone WHERE group_id = ? LIMIT 1",
                    (group_id,)
                ).fetchone()

            if not accounts:
                update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", "无账号", ttl=60)
                return

            # 主账号（用于执行登录逻辑）
            primary_account = accounts[0]
            rec_email = rec_email_row["email"] if rec_email_row else None
            rec_phone = rec_phone_row["phone"] if rec_phone_row else None

            token_uuid = None if force_relogin else _get_cached_token_uuid(group_id)
            msal_client = _create_msal_client(token_uuid)
            result = msal_client.acquire_token_by_automation(
                email=primary_account['email'],  # 传入 dict
                password = primary_account['password'],
                recovery_email=rec_email,
                recovery_phone=rec_phone
            )

            # 3. 处理结果 (直接写库，因为是低频高重要性数据)
            if result.get("success"):
                update_task_status(user_id, group_id, TASK_TYPE, "SUCCESS", "登录成功", ttl=60)
                # 如果自动化脚本修改了密码，这里需要更新数据库
                # 假设 result 包含 new_password 字段
                new_password = result.get("new_password")

                if new_password: # TODO
                    with get_db() as db:
                        begin_tx(db)
                        # 更新该组所有账号密码
                        db.execute(
                            "UPDATE accounts SET password = ? WHERE group_id = ?",
                            (new_password, group_id)
                        )
                        # 记录版本变更快照等逻辑...
                        commit_tx(db)

            else:
                msg = result.get("error", "登录失败")
                update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", msg, ttl=60)

        except Exception as e:
            update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", f"异常: {str(e)}", ttl=60)


# ================= 保活任务 (Beat) =================

@shared_task(name="tasks.maintenance_check")
def maintenance_check_task():
    """
    [定时任务] 每天检查一次，找出 >85 天未活动的账号进行保活
    """
    celery_logger.info("Running daily maintenance check...")

    try:
        # 1. 找出快过期的 group_id (这里假设你有 last_sync_time 字段)
        # 如果没有专门字段，可以用 mail_sync_state 表的 last_sync_time
        with get_db() as db:
            # 查找 mail_sync_state 中上次同步时间超过 85 天的
            query = """
                    SELECT group_id \
                    FROM mail_sync_state
                    WHERE last_sync_time < datetime('now', '-85 days') \
                    """
            rows = db.execute(query).fetchall()

        celery_logger.info(f"Found {len(rows)} groups needing maintenance")

        # 2. 触发轻量级同步任务
        for row in rows:
            # 使用 'check' 策略，只读一封邮件
            sync_group_task.delay(
                group_id=row["group_id"],
                user_id=0,  # 系统操作
                role="admin",
                strategy="check"
            )

    except Exception as e:
        celery_logger.error(f"Maintenance check failed: {e}")