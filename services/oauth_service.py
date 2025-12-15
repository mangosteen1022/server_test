"""OAuth 服务层 - 分离版"""

from services.tasks.worker import login_group_task, sync_group_task, _get_cached_token_uuid
from services.tasks.utils import update_task_status, get_task_status_raw, get_active_statuses_by_type
from utils.logger import get_logger
from celery_app import celery_app

logger = get_logger(__name__)

class OAuthService:

    # ==================== 登录相关 ====================

    def submit_group_login(self, group_id: str, user_id: int, role: str, force_relogin: bool = False) -> bool:
        task_type = "login"

        # 1. 去重 (只检查 login 类型的任务)
        current = get_task_status_raw(user_id, group_id, task_type)
        if current and current["status"] in ["PENDING", "RUNNING"]:
            return True

        # 2. 业务兜底 (Token有效则直接Success)
        if not force_relogin:
            token_uuid = _get_cached_token_uuid(group_id)
            if token_uuid:
                update_task_status(user_id, group_id, task_type, "SUCCESS", "已登录(缓存有效)", ttl=60)
                return True

        # 3. 提交
        update_task_status(user_id, group_id, task_type, "PENDING", "排队中...", ttl=3600)
        login_group_task.delay(
            group_id=group_id, user_id=user_id, role=role, force_relogin=force_relogin
        )
        return True

    def get_my_login_tasks(self, user_id: int):
        """获取我的登录任务状态"""
        return get_active_statuses_by_type(user_id, "login")

    # ==================== 同步相关 ====================

    def submit_sync(self, group_id: str, user_id: int, role: str, strategy: str = "auto") -> bool:
        task_type = "sync"

        # 1. 去重 (只检查 sync 类型的任务)
        current = get_task_status_raw(user_id, group_id, task_type)
        if current and current["status"] in ["PENDING", "RUNNING"]:
            return True

        # 2. 提交
        update_task_status(user_id, group_id, task_type, "PENDING", "排队中...", ttl=3600)
        sync_group_task.delay(
            group_id=group_id, user_id=user_id, role=role, strategy=strategy
        )
        return True

    def get_my_sync_tasks(self, user_id: int):
        """获取我的同步任务状态"""
        return get_active_statuses_by_type(user_id, "sync")

    # ==================== 取消相关 ====================

    def cancel_task_by_type(self, group_id: str, user_id: int, task_type: str):
        # 简单标记为失败，停止前端轮询
        update_task_status(user_id, group_id, task_type, "FAILURE", "已手动取消", ttl=60)
        return True