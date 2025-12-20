"""Celery 应用初始化配置"""
from celery import Celery
import settings

# 初始化 Celery
celery_app = Celery("mail_system", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
# 配置优化
celery_app.conf.update(
    result_expires=3600,         # 结果过期时间
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,

    # 【并发优化 - 针对 Threads 模式】
    # 既然是线程模式，预取可以稍微多一点，减少 Worker 空闲
    worker_prefetch_multiplier=4,

    # 防止内存泄漏 (Requests/MSAL 长时间运行可能会有微小泄漏)
    # 每个子进程/线程处理 500 个任务后重启
    worker_max_tasks_per_child=500,

    # 任务确认
    task_acks_late=True,
)

# Redis Key 定义 (保持之前设计的逻辑)
class RedisKeys:
    DB_WRITE_QUEUE = "sys:db_write_queue"
    DB_WRITE_FAILED = "sys:db_write_failed"
    USER_CONCURRENCY_PREFIX = "sys:concurrency:user:"
    TASK_STATUS_TEMPLATE = "sys:status:user:{user_id}:type:{task_type}:group:{group_id}"

# 自动发现任务
celery_app.autodiscover_tasks(['services.tasks.worker'])
celery_app.set_default()