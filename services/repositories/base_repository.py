"""基础仓储类 - 重构版，使用 DatabaseFactory"""

import sqlite3
from typing import Dict, List, Any, Optional, Union, Tuple
from abc import ABC, abstractmethod
from contextlib import contextmanager
import logging
from database.factory import get_db, begin_tx, commit_tx, rollback_tx

logger = logging.getLogger(__name__)


class BaseRepository(ABC):
    """基础仓储抽象类"""

    def __init__(self):
        """初始化仓储，不接收 db 连接"""
        pass

    @abstractmethod
    def get_table_name(self) -> str:
        """获取表名"""
        pass

    
    def execute_with_retry(self, query: str, params: Tuple = (), retries: int = 3):
        """带重试的执行SQL"""
        with get_db() as db:
            for attempt in range(retries):
                try:
                    return db.execute(query, params)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e).lower() and attempt < retries - 1:
                        logger.warning(f"Database locked, retrying (attempt {attempt + 1})")
                        continue
                    raise

    def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Dict]:
        """执行查询并返回单条记录"""
        with get_db() as db:
            cursor = db.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, query: str, params: Tuple = ()) -> List[Dict]:
        """执行查询并返回所有记录"""
        with get_db() as db:
            cursor = db.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def fetch_value(self, query: str, params: Tuple = ()) -> Any:
        """执行查询并返回单个值"""
        with get_db() as db:
            cursor = db.execute(query, params)
            row = cursor.fetchone()
            return row[0] if row else None

    def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """批量执行并返回影响的行数"""
        with get_db() as db:
            begin_tx(db)
            cursor = db.executemany(query, params_list)
            commit_tx(db)
            return cursor.rowcount

    def execute_update(self, query: str, params: Tuple = ()) -> int:
        """执行更新语句并返回影响的行数"""
        with get_db() as db:
            begin_tx(db)
            cursor = db.execute(query, params)
            commit_tx(db)
            return cursor.rowcount

    def exists(self, condition: str, params: Tuple = ()) -> bool:
        """检查记录是否存在"""
        query = f"SELECT 1 FROM {self.get_table_name()} WHERE {condition}"
        return self.fetch_value(query, params) is not None

    def count(self, condition: str = "1=1", params: Tuple = ()) -> int:
        """统计记录数"""
        query = f"SELECT COUNT(*) FROM {self.get_table_name()} WHERE {condition}"
        return self.fetch_value(query, params) or 0

    def build_where_clause(self, filters: Dict[str, Any]) -> Tuple[str, List]:
        """构建WHERE子句"""
        conditions = []
        params = []

        for field, value in filters.items():
            if value is None:
                continue
            elif isinstance(value, (list, tuple)):
                placeholders = ",".join(["?"] * len(value))
                conditions.append(f"{field} IN ({placeholders})")
                params.extend(value)
            elif isinstance(value, str) and "%" in value:
                conditions.append(f"{field} LIKE ?")
                params.append(value)
            else:
                conditions.append(f"{field} = ?")
                params.append(value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params

    def paginate(self, query: str, page: int, size: int, params: Tuple = ()) -> Dict[str, Any]:
        """分页查询"""
        offset = (page - 1) * size

        # 获取总数
        count_query = f"SELECT COUNT(*) FROM ({query}) as subq"
        total = self.fetch_value(count_query, params) or 0

        # 获取分页数据
        paginated_query = f"{query} LIMIT ? OFFSET ?"
        items = self.fetch_all(paginated_query, params + (size, offset))

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size
        }
