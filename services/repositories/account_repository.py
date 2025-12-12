"""账号数据仓储"""
import sqlite3
from typing import Dict, List, Any, Optional, Tuple
import json
from .base_repository import BaseRepository
from utils.logger import get_logger
from database.factory import get_db

logger = get_logger(__name__)


class AccountRepository(BaseRepository):
    """账号数据仓储类"""

    def __init__(self):
        super().__init__()

    def get_table_name(self) -> str:
        return "accounts"

    def find_by_id(self, account_id: int) -> Optional[Dict]:
        """根据ID查找账号"""
        return self.fetch_one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    def find_by_email(self, email: str) -> Optional[Dict]:
        """根据邮箱查找账号"""
        return self.fetch_one("SELECT * FROM accounts WHERE email = ? COLLATE NOCASE", (email,))

    def find_by_ids(self, account_ids: List[int]) -> List[Dict]:
        """根据ID列表查找账号"""
        if not account_ids:
            return []
        placeholders = ",".join(["?"] * len(account_ids))
        query = f"SELECT * FROM accounts WHERE id IN ({placeholders}) ORDER BY id"
        return self.fetch_all(query, tuple(account_ids))

    def insert(self, data: Dict) -> int:
        """插入记录并返回ID"""
        with get_db() as db:
            # 处理别名字段
            if 'aliases' in data and isinstance(data['aliases'], list):
                data = data.copy()
                data['aliases'] = json.dumps(data['aliases'])

            cursor = db.execute(f"""
                INSERT INTO {self.get_table_name()} ({', '.join(data.keys())})
                VALUES ({', '.join(['?'] * len(data))})
            """, tuple(data.values()))
            db.commit()
            return cursor.lastrowid

    def update_field(self, account_id: int, field: str, value: Any):
        """更新单个字段"""
        self.execute_update(f"UPDATE {self.get_table_name()} SET {field} = ? WHERE id = ?", (value, account_id))

    def delete(self, account_id: int):
        """删除记录"""
        with get_db() as db:
            begin_tx(db)
            db.execute(f"DELETE FROM {self.get_table_name()} WHERE id = ?", (account_id,))
            commit_tx(db)

    def update_fields(self, account_id: int, data: Dict) -> bool:
        """批量更新字段"""
        if not data:
            return False

        set_clause = ', '.join([f"{k} = ?" for k in data.keys()])
        query = f"UPDATE {self.get_table_name()} SET {set_clause} WHERE id = ?"

        try:
            self.execute_update(query, tuple(data.values()) + (account_id,))
            return True
        except Exception as e:
            logger.error(f"Failed to update account {account_id}: {str(e)}")
            return False

    def get_current_version(self, account_id: int) -> int:
        """获取当前版本号"""
        with get_db() as db:
            result = db.execute(
                "SELECT version FROM account_version WHERE account_id = ? ORDER BY version DESC LIMIT 1",
                (account_id,)
            ).fetchone()
            return result[0] if result else 0

    def update_status(self, account_id: int, status: str) -> bool:
        """更新状态"""
        try:
            self.update_field(account_id, "status", status)
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
        alias_contains: Optional[str] = None,
        note_contains: Optional[str] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        """带过滤条件的列表查询"""
        query = """
            SELECT DISTINCT a.*,
                   ar.recovery_email,
                   GROUP_CONCAT(arp.recovery_phone) as recovery_phones
            FROM accounts a
            LEFT JOIN account_recovery ar ON a.id = ar.account_id
            LEFT JOIN account_recovery_phone arp ON a.id = arp.account_id
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
            query += " AND ar.recovery_email LIKE ?"
            params.append(f"%{recovery_email_contains}%")

        if recovery_phone:
            query += " AND EXISTS(SELECT 1 FROM account_recovery_phone WHERE account_id = a.id AND recovery_phone = ?)"
            params.append(recovery_phone)

        if alias_contains:
            query += " AND a.aliases LIKE ?"
            params.append(f"%{alias_contains}%")

        if note_contains:
            query += " AND a.note LIKE ?"
            params.append(f"%{note_contains}%")

        if updated_after:
            query += " AND a.updated_at >= ?"
            params.append(updated_after)

        if updated_before:
            query += " AND a.updated_at <= ?"
            params.append(updated_before)

        query += " GROUP BY a.id, ar.recovery_email ORDER BY a.updated_at DESC"

        return self.paginate(query, page, size, tuple(params))