"""任务辅助工具 & 状态管理器"""
import json
import time
import redis
from contextlib import contextmanager
from typing import List, Dict, Optional

import settings
from celery_app import RedisKeys

redis_client = redis.from_url(settings.REDIS_URL)

# ==================== 状态管理 (带类型) ====================

def update_task_status(user_id: int, group_id: str, task_type: str, status: str, message: str, ttl: int = 3600):
    """
    更新任务状态 (区分 login/sync)
    task_type: 'login' | 'sync'
    """
    key = RedisKeys.TASK_STATUS_TEMPLATE.format(
        user_id=user_id, task_type=task_type, group_id=group_id
    )

    data = {
        "group_id": group_id,
        "type": task_type,
        "status": status,
        "message": message,
        "updated_at": int(time.time())
    }

    redis_client.setex(key, ttl, json.dumps(data))

def get_task_status_raw(user_id: int, group_id: str, task_type: str) -> Optional[Dict]:
    """获取原始状态 (用于同类型去重)"""
    key = RedisKeys.TASK_STATUS_TEMPLATE.format(
        user_id=user_id, task_type=task_type, group_id=group_id
    )
    val = redis_client.get(key)
    if val:
        try:
            return json.loads(val)
        except:
            return None
    return None

def get_active_statuses_by_type(user_id: int, task_type: str) -> List[Dict]:
    """
    [按类型扫描] 只扫描 login 或 sync 的状态
    Pattern: sys:status:user:{uid}:type:{target_type}:group:*
    """
    pattern = RedisKeys.TASK_STATUS_TEMPLATE.format(
        user_id=user_id, task_type=task_type, group_id="*"
    )

    cursor = '0'
    keys = []
    # 扫描匹配该类型的所有 Keys
    while True:
        cursor, batch = redis_client.scan(cursor=cursor, match=pattern, count=200)
        keys.extend(batch)
        if int(cursor) == 0:
            break

    if not keys:
        return []

    values = redis_client.mget(keys)
    results = []
    for val in values:
        if val:
            try:
                results.append(json.loads(val))
            except:
                pass

    return results

# ==================== 并发控制 (保持不变) ====================
class RedisSemaphore:
    def __init__(self, user_id: int, role: str):
        self.user_id = user_id
        self.limit = 30 if role == "admin" else 10
        self.key = f"{RedisKeys.USER_CONCURRENCY_PREFIX}{user_id}"

    def acquire(self) -> bool:
        current = redis_client.incr(self.key)
        if current > self.limit:
            redis_client.decr(self.key)
            return False
        return True

    def release(self):
        redis_client.decr(self.key)

@contextmanager
def user_concurrency_guard(task_instance, user_id: int, role: str):
    sem = RedisSemaphore(user_id, role)
    if not sem.acquire():
        raise task_instance.retry(countdown=5, max_retries=None)
    try:
        yield
    finally:
        sem.release()

def make_status_key(user_id, group_id, task_type):
    return f"task:{user_id}:{group_id}:{task_type}"

def get_task_status(user_id, group_id, task_type):
    """从 Redis 获取任务状态详情"""
    key = make_status_key(user_id, group_id, task_type)
    data = redis_client.get(key)
    if data:
        try:
            return json.loads(data)
        except:
            return None
    return None