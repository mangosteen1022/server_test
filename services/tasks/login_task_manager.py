"""登录任务管理器 - 重构版，基于 group_id"""

from typing import Dict, List, Optional, Any

from services.base.task_manager import BaseTaskManager
from services.token_service import TokenService
from services.mail_sync import MailSyncManager
from utils.logger import get_logger
from database.factory import get_db
import settings

logger = get_logger(__name__)


class LoginTaskManager(BaseTaskManager):
    """登录任务管理器"""

    def __init__(self):
        super().__init__(
            executor_name="login",
            max_workers=settings.CHECK_POOL_MAX_WORKERS,
            thread_name_prefix="login_"
        )
        self.token_service = TokenService()

    def submit_group_login(
        self,
        group_id: str,
        progress_callback: Optional[callable] = None,
        auto_sync: bool = True
    ) -> str:
        """
        提交邮箱组登录任务

        Args:
            group_id: 邮箱组ID
            progress_callback: 进度回调函数
            auto_sync: 登录成功后是否自动同步

        Returns:
            任务ID
        """
        # 使用 group_id 创建任务，避免重复任务
        task_key = f"login_{group_id}"

        task_data = {
            "group_id": group_id,
            "progress_callback": progress_callback,
            "auto_sync": auto_sync,
        }

        task_id = self.submit_task(
            task_key=task_key,
            task_type="login",
            task_data=task_data
        )

        return task_id

    def execute_task(
        self,
        task_id: str,
        task_key: str,
        task_type: str,
        task_data: Dict,
    ) -> None:
        """执行登录任务"""
        group_id = task_data.get("group_id")
        auto_sync = task_data.get("auto_sync", True)
        progress_callback = task_data.get("progress_callback")

        try:
            # 更新状态
            self.update_task_status(
                task_id,
                "running",
                f"[组 {group_id}] 正在登录..."
            )

            # 获取该组的账号
            with get_db() as db:
                accounts = db.execute(
                    "SELECT id, email FROM accounts WHERE group_id = ? ORDER BY id",
                    (group_id,)
                ).fetchall()

            if not accounts:
                self._handle_login_failure(
                    task_id,
                    "该组没有找到账号"
                )
                return

            # 批量登录
            success_count = 0
            total_count = len(accounts)

            for account in accounts:
                self.update_task_status(
                    task_id,
                    "running",
                    f"[组 {group_id}] 正在登录 {account['email']}..."
                )

                # 获取token
                token_uuid = self.token_service.get_cached_token_uuid(group_id)
                if token_uuid:
                    # Token已存在，验证是否有效
                    verification = self.token_service.verify_token(group_id)
                    if verification.get("valid"):
                        success_count += 1
                        if progress_callback:
                            progress_callback(group_id, f"账号 {account['email']} Token 有效")
                        continue

                # 尝试登录
                result = self._login_account(
                    account_id=account["id"],
                    progress_callback=progress_callback
                )

                if result.get("success"):
                    success_count += 1
                else:
                    logger.warning(f"Failed to login account {account['id']}: {result.get('error', 'Unknown error')}")

            # 检查是否至少有一个账号登录成功
            if success_count > 0:
                self._handle_login_success(task_id, success_count, total_count, auto_sync)
            else:
                self._handle_login_failure(task_id, "所有账号登录失败")

        except Exception as e:
            logger.error(f"Login task failed for group {group_id}: {str(e)}")
            self._handle_login_failure(
                task_id,
                f"登录异常: {str(e)}"
            )

    def _login_account(
        self,
        account_id: int,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """登录单个账号"""
        try:
            with get_db() as db:
                # 获取账号信息
                account = db.execute(
                    "SELECT email, password, group_id FROM accounts WHERE id = ?",
                    (account_id,)
                ).fetchone()

                if not account:
                    return {"success": False, "error": "账号不存在"}

                group_id = account["group_id"]

                # 获取恢复信息
                recovery_emails = [
                    row["email"]
                    for row in db.execute(
                        "SELECT email FROM account_recovery_email WHERE group_id = ? ORDER BY email",
                        (group_id,)
                    )
                ]

                recovery_phones = [
                    row["phone"]
                    for row in db.execute(
                        "SELECT phone FROM account_recovery_phone WHERE group_id = ? ORDER BY phone",
                        (group_id,)
                    )
                ]

            # 执行登录
            result = self.token_service.acquire_token_by_automation(
                account=account,
                recovery_email=recovery_emails[0] if recovery_emails else None,
                recovery_phone=recovery_phones[0] if recovery_phones else None
            )

            return result

        except Exception as e:
            logger.error(f"Failed to login account {account_id}: {str(e)}")
            return {"success": False, "error": str(e)}

    def _handle_login_success(self, task_id: str, success_count: int, total_count: int, auto_sync: bool = True):
        """处理登录成功"""
        message = f"登录成功: {success_count}/{total_count} 个账号"

        if auto_sync:
            message += "，准备自动同步..."

        self.complete_task(
            task_id,
            result={
                "success_count": success_count,
                "total_count": total_count
            },
            status="completed",
            message=message
        )

        # 如果需要自动同步，提交同步任务
        if auto_sync:
            try:
                from services.tasks.mail_sync_task_manager import MailSyncTaskManager
                sync_manager = MailSyncTaskManager()

                # 获取 group_id
                with get_db() as db:
                    first_account = db.execute(
                        "SELECT group_id FROM accounts LIMIT 1"
                    ).fetchone()

                    if first_account and first_account["group_id"]:
                        sync_manager.submit_group_sync(
                            group_id=first_account["group_id"],
                            strategy="auto",
                            progress_callback=lambda gid, msg: logger.info(f"[Login Auto Sync] {msg}")
                        )
                        message += "，已提交自动同步任务"

            except Exception as e:
                logger.error(f"Failed to submit auto-sync task: {str(e)}")

    def _handle_login_failure(self, task_id: str, error: str):
        """处理登录失败"""
        self.complete_task(
            task_id,
            status="failed",
            message=f"登录失败: {error}"
        )

    def cancel_group_login(self, group_id: str) -> bool:
        """取消邮箱组登录任务"""
        task_key = f"login_{group_id}"
        return self.cancel_task(task_key)

    def get_group_login_status(self, group_id: str) -> Optional[Dict]:
        """获取邮箱组登录状态"""
        task_key = f"login_{group_id}"
        return self.get_task_status(task_key)

    def list_login_tasks(self) -> List[Dict]:
        """列出所有登录任务"""
        tasks = self.list_tasks()
        login_tasks = []

        for task in tasks:
            if task.get("task_type") == "login":
                login_tasks.append({
                    "task_id": task["task_id"],
                    "task_key": task["task_key"],
                    "status": task["status"],
                    "group_id": task["task_data"].get("group_id"),
                    "created_at": task["created_at"],
                    "updated_at": task.get("updated_at"),
                    "result": task.get("result"),
                })

        return login_tasks