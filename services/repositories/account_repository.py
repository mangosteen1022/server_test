"""
services/repositories/account_repository.py
账号数据仓储 - 修复版
"""
import sqlite3
from typing import Dict, List, Any, Optional
import json
from .base_repository import BaseRepository
from utils.logger import get_logger
from database.factory import get_db, begin_tx, commit_tx, rollback_tx

logger = get_logger(__name__)


class AccountRepository(BaseRepository):
    """账号数据仓储类"""

    def __init__(self):
        super().__init__()

    def get_table_name(self) -> str:
        return "accounts"

    def find_by_id(self, account_id: int, db: Any = None) -> Optional[Dict]:
        """根据ID查找账号 (支持事务)"""
        return self.fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,), db=db)

    def find_by_email(self, email: str, db: Any = None) -> Optional[Dict]:
        """根据邮箱查找账号 (支持事务)"""
        return self.fetch_one("SELECT * FROM accounts WHERE email = ? COLLATE NOCASE", (email,), db=db)

    def find_by_ids(self, account_ids: List[int], db: Any = None) -> List[Dict]:
        """根据ID列表查找账号"""
        if not account_ids:
            return []
        placeholders = ",".join(["?"] * len(account_ids))
        query = f"SELECT * FROM accounts WHERE id IN ({placeholders}) ORDER BY id"
        return self.fetch_all(query, tuple(account_ids), db=db)

    def insert(self, data: Dict, db: Any = None) -> int:
        """
        插入记录并返回ID (修复：支持外部事务注入)
        """
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        query = f"INSERT INTO {self.get_table_name()} ({columns}) VALUES ({placeholders})"

        # 使用 BaseRepository 的连接管理器
        # 如果传入了 db，它会直接使用；如果没有，它会创建新连接
        with self._get_connection(db) as conn:
            cursor = conn.execute(query, tuple(data.values()))
            # 关键修复：如果是我们自己创建的连接(db is None)，我们负责提交
            # 如果是外部传入的事务连接，绝不能在这里提交！
            if db is None:
                conn.commit()
            return cursor.lastrowid

    def update_field(self, account_id: int, field: str, value: Any, db: Any = None):
        """更新单个字段 (支持事务)"""
        self.execute_update(
            f"UPDATE {self.get_table_name()} SET {field} = ? WHERE id = ?",
            (value, account_id),
            db=db
        )

    def delete(self, account_id: int, db: Any = None):
        """删除记录 (修复：支持事务)"""
        if db:
            # 如果在外部事务中，直接执行，不负责提交
            db.execute(f"DELETE FROM {self.get_table_name()} WHERE id = ?", (account_id,))
        else:
            # 独立事务
            with get_db() as conn:
                try:
                    begin_tx(conn)
                    conn.execute(f"DELETE FROM {self.get_table_name()} WHERE id = ?", (account_id,))
                    commit_tx(conn)
                except Exception as e:
                    rollback_tx(conn)
                    raise e

    def update_fields(self, account_id: int, data: Dict, db: Any = None) -> bool:
        """批量更新字段"""
        if not data: return False
        set_clause = ', '.join([f"{k} = ?" for k in data.keys()])
        query = f"UPDATE accounts SET {set_clause} WHERE id = ?"

        try:
            self.execute_update(query, tuple(data.values()) + (account_id,), db=db)
            return True
        except Exception as e:
            logger.error(f"Failed to update account {account_id}: {str(e)}")
            return False

    def get_current_version(self, account_id: int, db: Any = None) -> int:
        query = "SELECT version FROM account_version WHERE account_id = ? ORDER BY version DESC LIMIT 1"
        res = self.fetch_one(query, (account_id,), db=db)
        return res['version'] if res else 0

    def update_status(self, account_id: int, status: str, db: Any = None) -> bool:
        """更新状态"""
        try:
            self.update_field(account_id, "status", status, db=db)
            return True
        except Exception as e:
            logger.error(f"Failed to update status for account {account_id}: {str(e)}")
            return False

    def list_with_filters(
        self,
        page: int,
        size: int,
        status: Optional[str] = None,
        email_contains: Optional[str] = None,
        recovery_email_contains: Optional[str] = None,
        recovery_phone: Optional[str] = None,
        note_contains: Optional[str] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        """带过滤条件的列表查询 (修复关联逻辑)"""
        # 修复 1: 关联条件改为 group_id
        # 修复 2: 明确别名 recovery_email
        query = """
            SELECT DISTINCT a.*,
                   ar.email as recovery_email,
                   GROUP_CONCAT(arp.phone) as recovery_phones
            FROM accounts a
            LEFT JOIN account_recovery_email ar ON a.group_id = ar.group_id
            LEFT JOIN account_recovery_phone arp ON a.group_id = arp.group_id
            WHERE 1=1
        """
        params = []

        # 添加过滤条件
        if status:
            query += " AND a.status = ?"
            params.append(status)

        if email_contains:
            query += " AND a.email LIKE ?"
            params.append(f"%{email_contains}%")

        if recovery_email_contains:
            query += " AND ar.email LIKE ?"
            params.append(f"%{recovery_email_contains}%")

        if recovery_phone:
            # 修复 3: 子查询使用 group_id 关联
            query += " AND EXISTS(SELECT 1 FROM account_recovery_phone WHERE group_id = a.group_id AND phone = ?)"
            params.append(recovery_phone)

        # 注意：确认 accounts 表中是否有 note 列，如果没有会报错
        if note_contains:
            query += " AND a.note LIKE ?"
            params.append(f"%{note_contains}%")

        if updated_after:
            query += " AND a.updated_at >= ?"
            params.append(updated_after)

        if updated_before:
            query += " AND a.updated_at <= ?"
            params.append(updated_before)

        query += " GROUP BY a.id, ar.email ORDER BY a.updated_at DESC"

        # 调用 BaseRepository 的 paginate
        return self.paginate(query, page, size, tuple(params))