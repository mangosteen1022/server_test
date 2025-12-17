"""OAuth 服务层 - 分离版"""
import json
from typing import List, Dict

from celery_app import celery_app
from services.tasks.worker import login_group_task, sync_group_task, _get_cached_token_uuid, sync_folders_task
from services.tasks.utils import update_task_status, get_task_status_raw, get_active_statuses_by_type, redis_client, \
    get_task_status
from utils.logger import get_logger

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
        """
                取消指定类型的任务
                核心逻辑: 查Redis找TaskID -> Celery Revoke -> 更新Redis状态
                """
        # 1. 获取当前任务状态
        status = get_task_status(user_id, group_id, task_type)
        if not status:
            return False

        celery_task_id = status.get("task_id")

        # 2. 如果任务正在运行或排队，尝试撤销
        if celery_task_id and status.get("state") in ["PENDING", "RUNNING"]:
            try:
                # terminate=True: 强行终止正在执行的 Worker 进程 (SIGTERM)
                celery_app.control.revoke(celery_task_id, terminate=True)

                # 3. 立即更新 Redis 状态为 Cancelled，给前端反馈
                update_task_status(
                    user_id,
                    group_id,
                    task_type,
                    "CANCELLED",
                    "用户手动取消",
                    ttl=60
                )
                return True
            except Exception as e:
                print(f"Failed to revoke task {celery_task_id}: {e}")
                return False

        return False

    def get_my_login_tasks(self, user_id: int) -> List[Dict]:
        """获取某用户的所有登录任务状态"""
        return self._scan_tasks(user_id, "login")

    def get_my_sync_tasks(self, user_id: int) -> List[Dict]:
        """获取某用户的所有同步任务状态"""
        tasks = self._scan_tasks(user_id, "sync")
        return tasks

    def _scan_tasks(self, user_id: int, task_type: str) -> List[Dict]:
        """
        扫描 Redis 获取任务列表
        注意: KEYS 命令在生产环境慎用，这里假设用户量不大。
        更好的做法是用 SET 维护用户的 active tasks 列表。
        """
        pattern = f"task:{user_id}:*:{task_type}"
        keys = redis_client.keys(pattern)
        results = []

        for key in keys:
            data = redis_client.get(key)
            if data:
                try:
                    task_info = json.loads(data)
                    # 从 key 中解析 group_id: task:101:GROUP_ABC:login
                    parts = key.decode().split(":")
                    if len(parts) >= 3:
                        task_info["group_id"] = parts[2]
                    results.append(task_info)
                except:
                    continue
        return results

    def submit_folder_sync(self, group_id: str, user_id: int, role: str) -> str:
        """
        提交文件夹结构同步任务
        """
        task_type = "sync_folders"
        update_task_status(user_id, group_id, task_type, "PENDING", "准备更新目录...", ttl=600)
        task = sync_folders_task.delay(
            group_id=group_id,
            user_id=user_id,
            role=role
        )
        return task.id

