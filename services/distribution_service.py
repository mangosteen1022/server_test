"""
services/distribution_service.py
资源分配服务 - 处理项目与账号的分配逻辑
"""
import sqlite3
from typing import List, Dict, Any
from fastapi import HTTPException

from database.factory import get_db, begin_tx, commit_tx
from utils.logger import get_logger

logger = get_logger(__name__)


class DistributionService:
    """资源分配服务"""

    def list_projects(self) -> List[Dict]:
        """获取所有项目"""
        with get_db() as db:
            rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def create_project(self, name: str) -> int:
        """创建新项目"""
        try:
            with get_db() as db:
                cursor = db.execute("INSERT INTO projects (name) VALUES (?)", (name,))
                db.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(400, "项目名称已存在")

    def list_users(self) -> List[Dict]:
        """获取所有用户列表（用于分配目标）"""
        with get_db() as db:
            # 返回基本信息，不包含密码
            rows = db.execute("SELECT id, name, role, created_at FROM users ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def create_user(self, name: str, password: str, role: str = "user") -> int:
        """创建新用户"""
        try:
            with get_db() as db:
                cursor = db.execute(
                    "INSERT INTO users (name, password, role) VALUES (?, ?, ?)",
                    (name, password, role)
                )
                db.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(400, "用户名已存在")

    def get_project_stats(self, project_id: int) -> Dict:
        """统计该项目的分配情况"""
        with get_db() as db:
            # 1. 该项目已分配的总数
            total_assigned = db.execute(
                "SELECT COUNT(*) FROM project_assignments WHERE project_id = ?",
                (project_id,)
            ).fetchone()[0]

            # 2. 按用户分组的分配情况
            user_stats = db.execute("""
                                    SELECT u.name, COUNT(pa.id) as count
                                    FROM project_assignments pa
                                             JOIN users u ON pa.user_id = u.id
                                    WHERE pa.project_id = ?
                                    GROUP BY u.id, u.name
                                    """, (project_id,)).fetchall()

            # 3. 剩余可用账号（逻辑：系统总账号数 - 该项目已分配数）
            # 因为同一账号在同一项目中只能分配一次
            total_accounts = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            available = total_accounts - total_assigned

            return {
                "project_id": project_id,
                "total_assigned": total_assigned,
                "available_for_project": available,
                "user_stats": [dict(r) for r in user_stats]
            }

    def assign_accounts(self, project_id: int, user_id: int, count: int) -> int:
        """
        核心分配逻辑：
        从 accounts 表中筛选出【未分配给当前项目】的账号，分配给指定用户。
        """
        if count <= 0:
            raise HTTPException(400, "分配数量必须大于0")

        with get_db() as db:
            begin_tx(db)
            try:
                # 1. 筛选可用账号ID
                # 排除条件：该账号ID已经存在于 project_assignments 表中且 project_id 等于当前项目
                query = """
                        SELECT id \
                        FROM accounts
                        WHERE id NOT IN (SELECT account_id \
                                         FROM project_assignments \
                                         WHERE project_id = ?)
                        LIMIT ? \
                        """
                available_accounts = db.execute(query, (project_id, count)).fetchall()

                if len(available_accounts) < count:
                    actual = len(available_accounts)
                    raise HTTPException(
                        400,
                        f"资源不足！该项目剩余可用账号仅 {actual} 个，无法分配 {count} 个。"
                    )

                # 2. 批量插入分配记录
                assignments = [
                    (project_id, row["id"], user_id)
                    for row in available_accounts
                ]

                db.executemany("""
                               INSERT INTO project_assignments (project_id, account_id, user_id)
                               VALUES (?, ?, ?)
                               """, assignments)

                commit_tx(db)
                logger.info(f"Assigned {len(assignments)} accounts to user {user_id} for project {project_id}")
                return len(assignments)

            except Exception as e:
                # 如果是 HTTPException 直接抛出，其他的可能是数据库错误需要回滚
                if not isinstance(e, HTTPException):
                    logger.error(f"Assignment DB error: {e}")
                raise e