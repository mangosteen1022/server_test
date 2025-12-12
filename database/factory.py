"""数据库工厂单例 - 管理连接池"""

import sqlite3
import os
from contextlib import contextmanager
from typing import Generator
import threading
from queue import Queue, Empty, Full
from pathlib import Path
import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseFactory:
    """数据库工厂单例"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 防止重复初始化
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.db_path = Path(settings.DB_PATH)
        self._pool = Queue(maxsize=getattr(settings, 'DB_POOL_SIZE', 10))
        self._lock = threading.Lock()

        # 预创建一些连接
        for _ in range(min(5, getattr(settings, 'DB_POOL_SIZE', 10))):
            self._pool.put(self._create_connection())

        logger.info(f"DatabaseFactory initialized with pool size: {getattr(settings, 'DB_POOL_SIZE', 10)}")

    def _create_connection(self) -> sqlite3.Connection:
        """创建新的数据库连接"""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=getattr(settings, 'DB_TIMEOUT', 30)
        )

        # 启用WAL模式以提高并发性能
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.row_factory = sqlite3.Row

        return conn

    @contextmanager
    def get_db(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接的上下文管理器

        使用方式:
        with db_factory.get_db() as db:
            db.execute("SELECT * FROM accounts")
        """
        conn = None
        try:
            # 尝试从池中获取连接
            try:
                conn = self._pool.get(timeout=getattr(settings, 'DB_POOL_TIMEOUT', 5))
            except Empty:
                # 池中没有可用连接，创建新的
                logger.warning("Connection pool exhausted, creating new connection")
                conn = self._create_connection()

            yield conn

        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            if conn:
                # 发生错误时不将连接放回池中，而是关闭它
                try:
                    conn.close()
                except:
                    pass
                conn = None
            raise
        finally:
            if conn:
                try:
                    # 将连接放回池中
                    self._pool.put(conn, block=False)
                except Full:
                    # 池满了，直接关闭连接
                    conn.close()
                    logger.debug("Connection pool full, closing connection")

    def close_all(self):
        """关闭所有连接"""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break
        logger.info("All database connections closed")

    @classmethod
    def get_instance(cls) -> 'DatabaseFactory':
        """获取单例实例"""
        return cls()


# ==================== 数据库初始化函数 ====================

def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """检查表是否存在"""
    r = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (name,)).fetchone()
    return r is not None


def init_database(conn: sqlite3.Connection):
    """初始化数据库（执行schema.sql）"""
    if not table_exists(conn, "accounts"):
        with open(settings.SCHEMA_SQL, "r", encoding="utf-8") as f:
            conn.executescript(f.read())


def ensure_database_exists():
    """确保数据库文件存在且已初始化"""
    if not os.path.exists(settings.DB_PATH):
        # 创建数据库文件并初始化
        conn = None
        try:
            conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row

            # SQLite性能优化配置
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
            conn.execute("PRAGMA mmap_size=268435456;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA encoding='UTF-8';")

            # 初始化表结构
            init_database(conn)

            conn.commit()
        finally:
            if conn:
                conn.close()


# ==================== 事务辅助函数 ====================

def begin_tx(db: sqlite3.Connection):
    """开始事务"""
    db.execute("BEGIN IMMEDIATE")


def commit_tx(db: sqlite3.Connection):
    """提交事务"""
    db.commit()


def rollback_tx(db: sqlite3.Connection):
    """回滚事务"""
    try:
        db.rollback()
    except Exception:
        pass


# 确保数据库在模块加载时已初始化
ensure_database_exists()

# ==================== 工厂实例 ====================

# 创建全局实例
db_factory = DatabaseFactory.get_instance()

# 导出的便捷函数
@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """获取数据库连接的便捷函数"""
    with db_factory.get_db() as db:
        yield db


# FastAPI 依赖注入
def get_db_for_api() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI 依赖注入函数"""
    with get_db() as conn:
        yield conn


# 导出所有公共接口
__all__ = [
    "get_db",
    "get_db_for_api",
    "begin_tx",
    "commit_tx",
    "rollback_tx",
    "db_factory",
    "table_exists",
    "init_database",
]