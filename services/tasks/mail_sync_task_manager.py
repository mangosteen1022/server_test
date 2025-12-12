"""邮件同步任务管理器 - 重构版，基于 group_id"""

from typing import Dict, List, Optional, Any

from services.base.task_manager import BaseTaskManager
from services.token_service import TokenService
from utils.logger import get_logger
import settings

logger = get_logger(__name__)


class MailSyncTaskManager(BaseTaskManager):
    """邮件同步任务管理器"""

    def __init__(self):
        super().__init__(
            executor_name="mail_sync",
            max_workers=settings.CHECK_POOL_MAX_WORKERS,
            thread_name_prefix="mail_sync_"
        )
        self.token_service = TokenService()

    def submit_group_sync(
        self,
        group_id: str,
        strategy: str = "auto",
        progress_callback: Optional[callable] = None
    ) -> str:
        """
        提交邮箱组同步任务

        Args:
            group_id: 邮箱组ID
            strategy: 同步策略
            progress_callback: 进度回调函数

        Returns:
            任务ID
        """
        # 使用 group_id 创建任务，避免重复任务
        task_key = f"sync_{group_id}"

        task_data = {
            "group_id": group_id,
            "strategy": strategy,
            "progress_callback": progress_callback,
        }

        task_id = self.submit_task(
            task_key=task_key,
            task_type="mail_sync",
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
        """执行邮件同步任务"""
        group_id = task_data.get("group_id")
        strategy = task_data.get("strategy", "auto")
        progress_callback = task_data.get("progress_callback")

        try:
            # 更新状态
            self.update_task_status(
                task_id,
                "running",
                f"[组 {group_id}] 正在同步邮件..."
            )

            # 获取token
            token_uuid = self.token_service.get_cached_token_uuid(group_id)
            if not token_uuid:
                self._handle_sync_failure(
                    task_id,
                    "未找到token缓存，请先登录"
                )
                return

            # 创建MSAL客户端
            msal_client = self.token_service.create_msal_client(group_id, token_uuid)
            if not msal_client:
                self._handle_sync_failure(
                    task_id,
                    "无法创建MSAL客户端"
                )
                return

            # 执行同步
            sync_result = self._perform_sync(
                group_id,
                msal_client,
                strategy,
                task_id,
                progress_callback
            )

            if sync_result.get("success"):
                self._handle_sync_success(task_id, sync_result)
            else:
                self._handle_sync_failure(
                    task_id,
                    sync_result.get("error", "同步失败")
                )

        except Exception as e:
            logger.error(f"Mail sync task failed for group {group_id}: {str(e)}")
            self._handle_sync_failure(
                task_id,
                f"同步异常: {str(e)}"
            )

    def _perform_sync(
        self,
        group_id: str,
        msal_client,
        strategy: str,
        task_id: str,
        progress_callback: Optional[callable] = None,
    ) -> Dict:
        """执行实际的邮件同步"""
        from services.mail_sync import MailSyncManager

        # 创建同步管理器
        sync_manager = MailSyncManager()

        # 进度回调
        def internal_progress_callback(gid, msg):
            if gid == group_id:  # 确保只更新当前组的进度
                self.update_task_status(
                    task_id,
                    "running",
                    message=msg
                )
                if progress_callback:
                    progress_callback(gid, msg)

        # 执行同步（sync_group_mails 会自己管理数据库连接）
        result = sync_manager.sync_group_mails(
            group_id=group_id,
            msal_client=msal_client,
            strategy=strategy,
            progress_callback=internal_progress_callback
        )

        return result

    def _handle_sync_success(self, task_id: str, sync_result: Dict):
        """处理同步成功"""
        synced = sync_result.get("synced", 0)
        self.complete_task(
            task_id,
            result=sync_result,
            status="completed",
            message=f"同步完成，同步了 {synced} 封邮件"
        )

    def _handle_sync_failure(self, task_id: str, error: str):
        """处理同步失败"""
        self.complete_task(
            task_id,
            status="failed",
            message=f"同步失败: {error}"
        )

    def cancel_group_sync(self, group_id: str) -> bool:
        """取消邮箱组同步任务"""
        task_key = f"sync_{group_id}"
        return self.cancel_task(task_key)

    def get_group_sync_status(self, group_id: str) -> Optional[Dict]:
        """获取邮箱组同步状态"""
        task_key = f"sync_{group_id}"
        return self.get_task_status(task_key)

    def list_sync_tasks(self) -> List[Dict]:
        """列出所有同步任务"""
        tasks = self.list_tasks()
        sync_tasks = []

        for task in tasks:
            if task.get("task_type") == "mail_sync":
                sync_tasks.append({
                    "task_id": task["task_id"],
                    "task_key": task["task_key"],
                    "status": task["status"],
                    "group_id": task["task_data"].get("group_id"),
                    "strategy": task["task_data"].get("strategy"),
                    "created_at": task["created_at"],
                    "updated_at": task.get("updated_at"),
                    "result": task.get("result"),
                })

        return sync_tasks