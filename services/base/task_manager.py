"""任务管理器基类 - V2版，支持基于task_key的去重机制"""

import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field

from utils.time_utils import utc_now
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TaskStatus:
    """任务状态"""
    task_id: str
    task_key: str
    task_type: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    created_at: str = field(default_factory=lambda: utc_now())
    updated_at: Optional[str] = None
    result: Optional[Dict] = None
    message: Optional[str] = None
    task_data: Dict = field(default_factory=dict)


class BaseTaskManager(ABC):
    """任务管理器基类 - V2版

    支持基于task_key的任务去重机制
    每个task_key同时只能有一个活跃任务
    """

    def __init__(
        self,
        executor_name: str,
        max_workers: int,
        thread_name_prefix: str
    ):
        self.executor_name = executor_name
        self._executor: Optional[ThreadPoolExecutor] = None
        self._tasks: Dict[str, TaskStatus] = {}  # task_id -> TaskStatus
        self._task_keys: Dict[str, str] = {}  # task_key -> task_id (用于去重)
        self._lock = threading.Lock()
        self.max_workers = max_workers
        self.thread_name_prefix = thread_name_prefix

        # 初始化线程池
        self._init_executor()

    def _init_executor(self):
        """初始化线程池"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix=self.thread_name_prefix
            )
            logger.info(f"{self.executor_name} executor initialized with {self.max_workers} workers")

    @abstractmethod
    def execute_task(
        self,
        task_id: str,
        task_key: str,
        task_type: str,
        task_data: Dict
    ) -> None:
        """执行任务的抽象方法，子类必须实现"""
        pass

    def submit_task(
        self,
        task_key: str,
        task_type: str,
        task_data: Dict
    ) -> str:
        """提交任务

        Args:
            task_key: 任务键，用于去重
            task_type: 任务类型
            task_data: 任务数据

        Returns:
            task_id: 任务ID
        """
        with self._lock:
            # 检查是否已有相同task_key的任务在运行
            if task_key in self._task_keys:
                existing_task_id = self._task_keys[task_key]
                if existing_task_id in self._tasks:
                    existing_task = self._tasks[existing_task_id]
                    if existing_task.status in ["pending", "running"]:
                        logger.warning(f"Task already exists for key {task_key}, returning existing task_id")
                        return existing_task_id

            # 生成新的任务ID
            task_id = str(uuid.uuid4())

            # 创建任务状态
            task_status = TaskStatus(
                task_id=task_id,
                task_key=task_key,
                task_type=task_type,
                status="pending",
                task_data=task_data
            )

            # 保存任务
            self._tasks[task_id] = task_status
            self._task_keys[task_key] = task_id

            # 提交到线程池
            future = self._executor.submit(
                self._execute_with_wrapper,
                task_id,
                task_key,
                task_type,
                task_data
            )

            logger.info(f"Submitted task {task_id} with key {task_key}")
            return task_id

    def _execute_with_wrapper(
        self,
        task_id: str,
        task_key: str,
        task_type: str,
        task_data: Dict
    ):
        """任务执行的包装器，处理状态更新"""
        try:
            # 更新状态为运行中
            self.update_task_status(task_id, "running")

            # 调用子类的执行方法
            self.execute_task(task_id, task_key, task_type, task_data)

            # 如果任务没有被标记为完成或失败，则标记为完成
            current_status = self.get_task_status(task_id)
            if current_status and current_status["status"] == "running":
                self.update_task_status(task_id, "completed", "任务完成")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            self.update_task_status(task_id, "failed", f"任务执行失败: {str(e)}")
        finally:
            # 清理task_key映射（任务完成后）
            with self._lock:
                if task_key in self._task_keys and self._task_keys[task_key] == task_id:
                    del self._task_keys[task_key]

    def update_task_status(
        self,
        task_id: str,
        status: str,
        message: Optional[str] = None,
        result: Optional[Dict] = None
    ):
        """更新任务状态"""
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                task.status = status
                task.updated_at = utc_now()
                if message:
                    task.message = message
                if result:
                    task.result = result

                logger.debug(f"Updated task {task_id} status to {status}")

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                return {
                    "task_id": task.task_id,
                    "task_key": task.task_key,
                    "task_type": task.task_type,
                    "status": task.status,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                    "result": task.result,
                    "message": task.message,
                    "task_data": task.task_data
                }
            return None

    def get_task_status_by_key(self, task_key: str) -> Optional[Dict]:
        """通过task_key获取任务状态"""
        with self._lock:
            if task_key in self._task_keys:
                task_id = self._task_keys[task_key]
                return self.get_task_status(task_id)
            return None

    def cancel_task(self, task_key: str) -> bool:
        """取消任务"""
        with self._lock:
            if task_key in self._task_keys:
                task_id = self._task_keys[task_key]
                if task_id in self._tasks:
                    task = self._tasks[task_id]
                    if task.status in ["pending", "running"]:
                        task.status = "cancelled"
                        task.message = "任务已取消"
                        task.updated_at = utc_now()
                        logger.info(f"Cancelled task {task_id} with key {task_key}")
                        return True
            return False

    def list_tasks(self) -> List[Dict]:
        """列出所有任务"""
        with self._lock:
            return [
                {
                    "task_id": task.task_id,
                    "task_key": task.task_key,
                    "task_type": task.task_type,
                    "status": task.status,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                    "result": task.result,
                    "message": task.message,
                    "task_data": task.task_data
                }
                for task in self._tasks.values()
            ]

    def complete_task(
        self,
        task_id: str,
        status: str = "completed",
        message: Optional[str] = None,
        result: Optional[Dict] = None
    ):
        """完成任务（由子类调用）"""
        self.update_task_status(task_id, status, message, result)

    def get_pool_stats(self) -> Dict:
        """获取线程池统计"""
        with self._lock:
            running_tasks = sum(
                1 for task in self._tasks.values()
                if task.status == "running"
            )
            pending_tasks = sum(
                1 for task in self._tasks.values()
                if task.status == "pending"
            )
            return {
                "running_tasks": running_tasks,
                "pending_tasks": pending_tasks,
                "total_tasks": len(self._tasks),
                "active_task_keys": len(self._task_keys),
                "max_workers": self.max_workers,
                "executor_name": self.executor_name
            }

    def cleanup_expired_tasks(self, hours: int = 1) -> int:
        """清理过期的任务记录"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        cutoff_str = cutoff_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        cleaned = 0
        with self._lock:
            expired_tasks = []
            for task_id, task in self._tasks.items():
                if (task.created_at < cutoff_str and
                    task.status in ["completed", "failed", "cancelled"]):
                    expired_tasks.append(task_id)

            for task_id in expired_tasks:
                # 清理task_key映射
                if task_id in self._tasks:
                    task = self._tasks[task_id]
                    if task.task_key in self._task_keys:
                        if self._task_keys[task.task_key] == task_id:
                            del self._task_keys[task.task_key]

                # 清理任务
                del self._tasks[task_id]
                cleaned += 1

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired {self.executor_name} tasks")

        return cleaned

    def shutdown(self, wait: bool = True):
        """关闭线程池"""
        if self._executor:
            self._executor.shutdown(wait=wait)
            logger.info(f"{self.executor_name} executor shutdown")

    def __del__(self):
        """析构函数"""
        self.shutdown(wait=False)