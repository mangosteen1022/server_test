"""优化后的邮箱认证服务层 - 重构版，基于 group_id"""

from typing import Dict, List, Optional, Any

from .token_service import TokenService
from .tasks.login_task_manager import LoginTaskManager
from .tasks.mail_sync_task_manager import MailSyncTaskManager
from utils.logger import get_logger
from database.factory import get_db

logger = get_logger(__name__)


class AuthService:
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

    def submit_group_login_by_account_ids(
        self,
        account_ids: List[int],
        progress_callback: Optional[callable] = None,
        auto_sync: bool = True
    ) -> Dict[str, str]:
        """通过账号ID提交登录任务（按组分组）

        Args:
            account_ids: 账号ID列表
            progress_callback: 进度回调函数
            auto_sync: 登录成功后是否自动同步邮件

        Returns:
            {group_id: task_id} 映射
        """
        if not account_ids:
            return {}

        # 按组分组账号
        groups = {}
        with get_db() as db:
            for account_id in account_ids:
                account = db.execute(
                    "SELECT id, group_id FROM accounts WHERE id = ?",
                    (account_id,)
                ).fetchone()
                if account and account["group_id"]:
                    group_id = account["group_id"]
                    if group_id not in groups:
                        groups[group_id] = []
                    groups[group_id].append(account_id)

        # 为每个组提交登录任务
        task_ids = {}
        for group_id, ids in groups.items():
            task_ids[group_id] = self.submit_group_login(
                group_id=group_id,
                progress_callback=progress_callback,
                auto_sync=auto_sync
            )

        logger.info(f"Submitted {len(task_ids)} login tasks for groups: {list(task_ids.keys())}")
        return task_ids

    def get_login_task_status(self, task_id: str) -> Optional[Dict]:
        """获取登录任务状态"""
        return self.login_manager.get_task_status(task_id)

    def cancel_group_login(self, group_id: str) -> bool:
        """取消邮箱组登录任务"""
        cancelled = self.login_manager.cancel_group_login(group_id)
        logger.info(f"Cancelled login task for group {group_id}: {cancelled}")
        return cancelled

    def cancel_group_login_by_account_id(self, account_id: int) -> bool:
        """通过账号ID取消登录任务"""
        with get_db() as db:
            account = db.execute(
                "SELECT group_id FROM accounts WHERE id = ?",
                (account_id,)
            ).fetchone()

            if account and account["group_id"]:
                return self.cancel_group_login(account["group_id"])
            return False

    def list_login_tasks(self) -> List[Dict]:
        """列出所有登录任务"""
        return self.login_manager.list_login_tasks()

    # ==================== 邮件同步任务相关 ====================

    def submit_group_sync(
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

    def submit_group_sync_by_account_ids(
        self,
        account_ids: List[int],
        strategy: str = "auto",
        progress_callback: Optional[callable] = None
    ) -> Dict[str, str]:
        """通过账号ID提交同步任务（按组分组）

        Args:
            account_ids: 账号ID列表
            strategy: 同步策略
            progress_callback: 进度回调函数

        Returns:
            {group_id: task_id} 映射
        """
        if not account_ids:
            return {}

        # 按组分组账号
        groups = {}
        with get_db() as db:
            for account_id in account_ids:
                account = db.execute(
                    "SELECT id, group_id FROM accounts WHERE id = ?",
                    (account_id,)
                ).fetchone()
                if account and account["group_id"]:
                    group_id = account["group_id"]
                    if group_id not in groups:
                        groups[group_id] = []
                    groups[group_id].append(account_id)

        # 为每个组提交同步任务
        task_ids = {}
        for group_id, ids in groups.items():
            task_ids[group_id] = self.submit_group_sync(
                group_id=group_id,
                strategy=strategy,
                progress_callback=progress_callback
            )

        logger.info(f"Submitted {len(task_ids)} sync tasks for groups: {list(task_ids.keys())}")
        return task_ids

    def get_sync_task_status(self, task_id: str) -> Optional[Dict]:
        """获取同步任务状态"""
        return self.mail_sync_manager.get_task_status(task_id)

    def cancel_group_sync(self, group_id: str) -> bool:
        """取消邮箱组同步任务"""
        cancelled = self.mail_sync_manager.cancel_group_sync(group_id)
        logger.info(f"Cancelled sync task for group {group_id}: {cancelled}")
        return cancelled

    def cancel_group_sync_by_account_id(self, account_id: int) -> bool:
        """通过账号ID取消同步任务"""
        with get_db() as db:
            account = db.execute(
                "SELECT group_id FROM accounts WHERE id = ?",
                (account_id,)
            ).fetchone()

            if account and account["group_id"]:
                return self.cancel_group_sync(account["group_id"])
            return False

    def list_sync_tasks(self) -> List[Dict]:
        """列出所有同步任务"""
        return self.mail_sync_manager.list_sync_tasks()

    # ==================== Token管理 ====================

    def verify_group_token(self, group_id: str) -> Dict:
        """验证邮箱组的token

        Args:
            group_id: 邮箱组ID

        Returns:
            验证结果
        """
        return self.token_service.verify_token(group_id)

    def get_group_token_info(self, group_id: str) -> Dict:
        """获取邮箱组的token信息

        Args:
            group_id: 邮箱组ID

        Returns:
            token信息
        """
        token_uuid = self.token_service.get_cached_token_uuid(group_id)
        if not token_uuid:
            return {"valid": False, "error": "未找到token缓存"}

        return {
            "group_id": group_id,
            "token_uuid": token_uuid,
            "valid": True
        }

    def revoke_group_token(self, group_id: str) -> bool:
        """撤销邮箱组的token

        Args:
            group_id: 邮箱组ID

        Returns:
            是否成功
        """
        success = self.token_service.delete_token_cache(group_id)
        if success:
            logger.info(f"Revoked token for group {group_id}")
        return success

    def get_all_token_caches(self) -> List[Dict]:
        """获取所有token缓存信息"""
        return self.token_service.get_all_token_caches()

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