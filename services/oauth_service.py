"""优化后的邮箱认证服务层 - 重构版，基于 group_id"""

from typing import Dict, List, Optional, Any

from .token_service import TokenService
from .tasks.login_task_manager import LoginTaskManager
from .tasks.mail_sync_task_manager import MailSyncTaskManager
from utils.logger import get_logger
from database.factory import get_db

logger = get_logger(__name__)


class OAuthService:
    """优化后的邮箱认证服务 - 重构版，基于 group_id

    通过组合不同的任务管理器来处理登录和邮件同步任务，
    基于 group_id 避免重复任务。
    """

    def __init__(self):
        """初始化认证服务"""
        self.token_service = TokenService()
        self.login_manager = LoginTaskManager()
        self.mail_sync_manager = MailSyncTaskManager()

    # ==================== 登录任务相关 ====================

    def submit_group_login(
        self,
        group_id: str,
        progress_callback: Optional[callable] = None,
        auto_sync: bool = True
    ) -> str:
        """提交邮箱组登录任务

        Args:
            group_id: 邮箱组ID
            progress_callback: 进度回调函数
            auto_sync: 登录成功后是否自动同步邮件

        Returns:
            task_id: 任务ID
        """
        logger.info(f"Submitting login task for group {group_id}")
        return self.login_manager.submit_group_login(
            group_id=group_id,
            progress_callback=progress_callback,
            auto_sync=auto_sync
        )

    def get_login_task_status(self, task_id: str) -> Optional[Dict]:
        """获取登录任务状态"""
        return self.login_manager.get_task_status(task_id)

    def cancel_login(self, group_id: str) -> bool:
        """取消邮箱组登录任务"""
        cancelled = self.login_manager.cancel_group_login(group_id)
        logger.info(f"Cancelled login task for group {group_id}: {cancelled}")
        return cancelled

    # ==================== 邮件同步任务相关 ====================

    def submit_sync(
        self,
        group_id: str,
        strategy: str = "auto",
        progress_callback: Optional[callable] = None
    ) -> str:
        """提交邮箱组邮件同步任务

        Args:
            group_id: 邮箱组ID
            strategy: 同步策略
            progress_callback: 进度回调函数

        Returns:
            task_id: 任务ID
        """
        logger.info(f"Submitting sync task for group {group_id}")
        return self.mail_sync_manager.submit_group_sync(
            group_id=group_id,
            strategy=strategy,
            progress_callback=progress_callback
        )


    def get_sync_task_status(self, task_id: str) -> Optional[Dict]:
        """获取同步任务状态"""
        return self.mail_sync_manager.get_task_status(task_id)

    def cancel_group_sync(self, group_id: str) -> bool:
        """取消邮箱组同步任务"""
        cancelled = self.mail_sync_manager.cancel_group_sync(group_id)
        logger.info(f"Cancelled sync task for group {group_id}: {cancelled}")
        return cancelled

    # ==================== 批量操作 ====================

    def sync_selected_accounts(
        self,
        account_ids: List[int],
        strategy: str = "auto",
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """同步选中的账号

        Args:
            account_ids: 账号ID列表
            strategy: 同步策略
            progress_callback: 进度回调函数

        Returns:
            操作结果
        """
        if not account_ids:
            return {"success": False, "error": "没有选择账号"}

        # 提交登录任务
        login_tasks = self.submit_group_login_by_account_ids(
            account_ids=account_ids,
            progress_callback=progress_callback,
            auto_sync=False  # 手动控制同步
        )

        # 提交同步任务
        sync_tasks = self.submit_group_sync_by_account_ids(
            account_ids=account_ids,
            strategy=strategy,
            progress_callback=progress_callback
        )

        return {
            "success": True,
            "login_tasks": login_tasks,
            "sync_tasks": sync_tasks,
            "total_groups": len(login_tasks)
        }

    def sync_all_accounts(
        self,
        strategy: str = "auto",
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """同步所有账号

        Args:
            strategy: 同步策略
            progress_callback: 进度回调函数

        Returns:
            操作结果
        """
        # 获取所有账号
        with get_db() as db:
            accounts = db.execute("SELECT id FROM accounts").fetchall()
            account_ids = [row["id"] for row in accounts]

        return self.sync_selected_accounts(
            account_ids=account_ids,
            strategy=strategy,
            progress_callback=progress_callback
        )