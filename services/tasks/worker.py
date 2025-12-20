"""
Celery Worker 任务定义
"""
import time
from typing import List, Optional, Dict

import settings
from celery.utils.log import get_task_logger

from auth.msal_client import MSALClient
from celery_app import celery_app
from services import MailService
from services.mail_sync import MailSyncManager
from services.tasks.utils import user_concurrency_guard, update_task_status
from database.factory import get_db, begin_tx, commit_tx
from utils.logger import get_logger

# 使用 Celery 的 Logger
celery_logger = get_task_logger(__name__)
sys_logger = get_logger(__name__)

def _create_msal_client(group_id: str):
    """
    直接创建 MSAL 客户端
    不再依赖 token_uuid，直接通过 group_id 操作 account_token 表
    """
    return MSALClient(
        client_id=settings.MSAL_CLIENT_ID,
        authority=settings.MSAL_AUTHORITY,
        scopes=settings.MSAL_SCOPES,
        group_id=group_id,
        default_port=settings.MSAL_REDIRECT_PORT
    )
def get_token_from_db(group_id) -> Optional[Dict]:
    """从数据库读取 Token 记录"""
    try:
        with get_db() as db:
            row = db.execute(
                """
                SELECT access_token, refresh_token, at_expires_at 
                FROM account_token 
                WHERE group_id = ?
                """,
                (group_id,)
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        return None
# ================= 邮件同步任务 =================

@celery_app.task(bind=True, name="tasks.sync_group")
def sync_group_task(self, group_id: str, user_id: int, role: str, strategy: str = "auto"):
    """同步任务"""
    TASK_TYPE = "sync"
    update_task_status(
        user_id, group_id, TASK_TYPE, "RUNNING", "初始化同步...",
        ttl=3600, task_id=self.request.id
    )

    with user_concurrency_guard(self, user_id, role):
        try:
            # 回调闭包
            def progress_callback(gid, msg):
                update_task_status(user_id, gid, TASK_TYPE, "RUNNING", msg, ttl=3600)

            msal_client = _create_msal_client(group_id)
            manager = MailSyncManager()

            result = manager.sync_group_mails(
                group_id=group_id,
                msal_client=msal_client,
                strategy=strategy,
                cb=progress_callback
            )

            status = "SUCCESS" if result.get("success") else "FAILURE"
            msg = result.get("message", "同步完成")
            if result.get("error"): msg = f"错误: {result['error']}"

            update_task_status(user_id, group_id, TASK_TYPE, status, msg, ttl=60)

        except Exception as e:
            celery_logger.error(f"Sync error: {e}")
            update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", str(e), ttl=60)


# ================= 登录任务 =================

@celery_app.task(bind=True, name="tasks.login_group")
def login_group_task(self, group_id: str, user_id: int, role: str, force_relogin: bool = False):
    """
    异步登录任务
    注意：登录涉及密码修改和Token更新，这部分数据至关重要，
    因此我们在 Worker 中直接写入数据库，不走 Redis 队列。
    """
    TASK_TYPE = "login"
    update_task_status(
        user_id, group_id, TASK_TYPE, "RUNNING", "正在登录...",
        ttl=3600, task_id=self.request.id
    )
    with user_concurrency_guard(self, user_id, role):
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

            msal_client = _create_msal_client(group_id)
            if force_relogin:
                msal_client.logout()

            result = msal_client.acquire_token_by_automation(
                email=primary_account['email'],  # 传入 dict
                password=primary_account['password'],
                recovery_email=rec_email,
                recovery_phone=rec_phone
            )

            # 3. 处理结果 (直接写库，因为是低频高重要性数据)
            if result.get("success"):
                update_task_status(user_id, group_id, TASK_TYPE, "SUCCESS", "登录成功", ttl=60)
                sync_manager = MailSyncManager()
                folder_res = sync_manager.sync_folders(group_id, msal_client)
                if folder_res["success"]:
                    msg = f"登录成功 (目录: {folder_res['count']}个)"
                else:
                    msg = f"登录成功 (目录同步失败: {folder_res.get('error')})"
                update_task_status(user_id, group_id, TASK_TYPE, "SUCCESS", msg, ttl=60)
                # TODO 更新的数据保存,快照更新
                # 如果自动化脚本修改了密码，这里需要更新数据库
                # 假设 result 包含 new_password 字段
                new_password = result.get("new_password")
                if new_password:
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

@celery_app.task(name="tasks.maintenance_check")
def maintenance_check_task():
    """
    [定时任务] 每天检查一次，找出 >85 天未活动的账号进行保活
    """
    celery_logger.info("Running daily maintenance check...")

    try:
        # 1. 找出快过期的 group_id (这里假设你有 last_sync_time 字段)
        # 如果没有专门字段，可以用 mail_sync_state 表的 last_sync_time
        threshold = int(time.time()) + (5 * 86400)
        with get_db() as db:
            # 查找 mail_sync_state 中上次同步时间超过 85 天的
            query = "SELECT group_id FROM account_token WHERE rt_expires_at < ?"
            rows = db.execute(query, (threshold,)).fetchall()

        celery_logger.info(f"Found {len(rows)} groups needing maintenance")

        # 2. 触发轻量级同步任务
        for row in rows:
            sync_group_task.delay(
                group_id=row["group_id"],
                user_id=0,  # 系统操作
                role="admin",
                strategy="check"
            )

    except Exception as e:
        celery_logger.error(f"Maintenance check failed: {e}")


# 同步文件夹任务
@celery_app.task(bind=True, name="tasks.sync_folders")
def sync_folders_task(self, group_id: str, user_id: int, role: str):
    """手动同步文件夹结构"""
    TASK_TYPE = "sync_folders"  # 使用独立的任务类型，避免混淆
    update_task_status(
        user_id, group_id, TASK_TYPE, "RUNNING", "正在更新目录...",
        ttl=3600, task_id=self.request.id
    )

    with user_concurrency_guard(self, user_id, role):
        try:
            client = _create_msal_client(group_id)
            if not client.get_access_token():
                update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", "未登录", ttl=60)
                return
            manager = MailSyncManager()
            res = manager.sync_folders(group_id, client)
            if res["success"]:
                update_task_status(user_id, group_id, TASK_TYPE, "SUCCESS", f"目录更新完成 ({res['count']}个)", ttl=60)
            else:
                update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", f"失败: {res.get('error')}", ttl=60)

        except Exception as e:
            update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", str(e), ttl=60)


@celery_app.task(bind=True, name="tasks.batch_download")
def batch_download_task(self, user_id: int, message_ids: List[int], group_id: str = "GLOBAL"):
    TASK_TYPE = "download"
    update_task_status(
        user_id, group_id, TASK_TYPE, "RUNNING",
        f"准备下载 {len(message_ids)} 封邮件...",
        ttl=3600,
        task_id=self.request.id
    )
    try:
        service = MailService()

        # 定义进度回调 (让 Service 层在多线程下载时能汇报进度)
        def progress_callback(current, total):
            update_task_status(
                user_id, group_id, TASK_TYPE, "RUNNING",
                f"正在下载({current}/{total})",
                ttl=3600
            )

        # 2. 执行业务逻辑 (这里面依然用 ThreadPoolExecutor 加速)
        result = service.batch_download_content(
            message_ids,
            progress_callback=progress_callback
        )

        # 3. 处理结果
        if result["success"]:
            msg = f"下载完成: 成功 {result['downloaded']}, 跳过 {result['skipped']}"
            if result['errors']:
                msg += f", 失败 {len(result['errors'])}"
            update_task_status(user_id, group_id, TASK_TYPE, "SUCCESS", msg, ttl=60)
        else:
            update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", result.get("message"), ttl=60)

    except Exception as e:
        update_task_status(user_id, group_id, TASK_TYPE, "FAILURE", f"异常: {str(e)}", ttl=60)