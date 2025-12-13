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

    @abstractmethod
    def get_table_name(self) -> str:
        """获取表名"""
        pass

    @contextmanager
    def _get_connection(self, db: Optional[sqlite3.Connection] = None):
        """
        上下文管理器：如果传入了外部 db，则直接使用（不关闭）；
        否则创建新的 db 连接（自动关闭）。
        """
        if db:
            yield db
        else:
            with get_db() as conn:
                yield conn

    def fetch_one(self, query: str, params: Tuple = (), db: Optional[sqlite3.Connection] = None) -> Optional[Dict]:
        with self._get_connection(db) as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, query: str, params: Tuple = (), db: Optional[sqlite3.Connection] = None) -> List[Dict]:
        with self._get_connection(db) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def fetch_value(self, query: str, params: Tuple = (), db: Optional[sqlite3.Connection] = None) -> Any:
        """执行查询并返回单个值"""
        with self._get_connection(db) as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return row[0] if row else None

    def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """批量执行并返回影响的行数 (修复事务安全)"""
        with get_db() as db:
            try:
                begin_tx(db)
                cursor = db.executemany(query, params_list)
                commit_tx(db)
                return cursor.rowcount
            except Exception as e:
                rollback_tx(db)
                logger.error(f"execute_many failed: {e}")
                raise

    def execute_update(self, query: str, params: Tuple = (), db: Optional[sqlite3.Connection] = None) -> int:
        """执行更新语句并返回影响的行数"""
        if db:
            cursor = db.execute(query, params)
            return cursor.rowcount
        else:
            with get_db() as conn:
                try:
                    begin_tx(conn)
                    cursor = conn.execute(query, params)
                    commit_tx(conn)
                    return cursor.rowcount
                except Exception as e:
                    rollback_tx(conn)
                    raise e

    def exists(self, condition: str, params: Tuple = (), db: Optional[sqlite3.Connection] = None) -> bool:
        """检查记录是否存在"""
        query = f"SELECT 1 FROM {self.get_table_name()} WHERE {condition}"
        return self.fetch_value(query, params, db) is not None

    def count(self, condition: str = "1=1", params: Tuple = (), db: Optional[sqlite3.Connection] = None) -> int:
        query = f"SELECT COUNT(*) FROM {self.get_table_name()} WHERE {condition}"
        row = self.fetch_one(query, params, db)
        # fetch_one 返回 dict，取第一个值
        return list(row.values())[0] if row else 0

    def build_where_clause(self, filters: Dict[str, Any]) -> Tuple[str, List]:
        """构建WHERE子句"""
        """构建WHERE子句 (修复 NULL 值处理)"""
        conditions = []
        params = []

        for field, value in filters.items():
            # 修复：支持 IS NULL 查询
            if value is None:
                continue

            if isinstance(value, (list, tuple)):
                if not value:  # 处理空列表
                    continue
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

    def paginate(self, query: str, page: int, size: int, params: Tuple = (), db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        page = max(1, page)
        size = max(1, size)
        offset = (page - 1) * size
        # 获取总数
        count_query = f"SELECT COUNT(*) FROM ({query}) as subq"

        # 注意：这里需要手动执行 fetch_one 的逻辑，因为 query 可能是复杂 SQL
        with self._get_connection(db) as conn:
            total_cursor = conn.execute(count_query, params)
            total_row = total_cursor.fetchone()
            total = total_row[0] if total_row else 0

            # 获取分页数据
            paginated_query = f"{query} LIMIT ? OFFSET ?"
            cursor = conn.execute(paginated_query, params + (size, offset))
            items = [dict(row) for row in cursor.fetchall()]

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size
        }