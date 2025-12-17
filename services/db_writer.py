"""
数据库异步批量写入守护进程 (Write-Behind Daemon)
功能：从 Redis 队列捞取数据 -> 批量写入 SQLite
"""
import time
import json
import logging
import traceback
from typing import List, Dict, Any

import redis
from sqlalchemy import text

# 引入你的数据库工具
from database.factory import get_db, begin_tx, commit_tx
import settings
from celery_app import RedisKeys

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DB_WRITER")

# 连接 Redis
redis_client = redis.from_url(settings.REDIS_URL)

BATCH_SIZE = 500  # 每次批量写入的条数
FLUSH_INTERVAL = 2.0  # 最长等待时间 (秒)，防止数据积压太久


def run_db_writer():
    logger.info("🚀 DB Writer Daemon started... Waiting for data.")

    pending_items = []
    last_flush_time = time.time()

    while True:
        try:
            # 1. 非阻塞捞取数据
            # RPOP 相比 BLPOP 更容易控制 flush 间隔
            raw_data = redis_client.rpop(RedisKeys.DB_WRITE_QUEUE)

            if raw_data:
                pending_items.append(raw_data)
            else:
                # 队列空了，休息一下避免 CPU 100%
                time.sleep(0.1)

            # 2. 检查是否需要触发写入 (数量够了 OR 时间到了)
            current_time = time.time()
            is_batch_full = len(pending_items) >= BATCH_SIZE
            is_timeout = (len(pending_items) > 0) and (current_time - last_flush_time >= FLUSH_INTERVAL)

            if is_batch_full or is_timeout:
                _flush_buffer(pending_items)
                pending_items = []  # 清空缓冲区
                last_flush_time = current_time

        except Exception as e:
            logger.error(f"Critical Loop Error: {e}")
            time.sleep(5)  # 出错后冷却


def _flush_buffer(raw_items: List[bytes]):
    """执行批量写入逻辑"""
    if not raw_items:
        return

    # 按表分组数据
    # 结构: { "mail_message": [dict1, dict2], "mail_body": [...] }
    grouped_data: Dict[str, List[Dict[str, Any]]] = {}

    # 临时保存解析失败的 item 以便重试（可选）
    failed_items = []

    for raw in raw_items:
        try:
            # 数据协议: {"table": "table_name", "data": {...}}
            payload = json.loads(raw)
            table_name = payload.get("table")
            row_data = payload.get("data")

            if table_name and row_data:
                if table_name not in grouped_data:
                    grouped_data[table_name] = []
                grouped_data[table_name].append(row_data)
        except Exception:
            logger.error("Failed to parse JSON item, discarding.")
            continue

    if not grouped_data:
        return

    # 开始数据库事务
    try:
        start_t = time.time()
        with get_db() as db:
            begin_tx(db)
            total_records = 0
            for table, rows in grouped_data.items():
                if not rows:
                    continue
                keys = list(rows[0].keys())
                columns = ", ".join(keys)
                placeholders = ", ".join(["?" for _ in keys])
                action = "INSERT OR REPLACE" if table == "mail_body" else "INSERT OR IGNORE"
                sql = f"{action} INTO {table} ({columns}) VALUES ({placeholders})"
                values_list = []
                for row in rows:
                    values_list.append(tuple(row[k] for k in keys))
                db.executemany(sql, values_list)
                total_records += len(rows)

            # E. 提交事务
            commit_tx(db)

            duration = time.time() - start_t
            logger.info(f"✅ Flushed {total_records} records (Tables: {list(grouped_data.keys())}) in {duration:.3f}s")

    except Exception as e:
        logger.error(f"❌ DB Write Failed: {e}")
        # 紧急避险：将数据塞回 Redis 队列头部 (Lpush)，防止数据丢失
        # 注意：这可能会导致死循环如果数据本身有问题，生产环境需要 Dead Letter Queue (死信队列)
        logger.warning(f"Re-queuing {len(raw_items)} items...")

        pipe = redis_client.pipeline()
        for item in raw_items:
            pipe.lpush(RedisKeys.DB_WRITE_QUEUE, item)
        pipe.execute()


if __name__ == "__main__":
    # 可以直接运行此文件启动守护进程
    run_db_writer()