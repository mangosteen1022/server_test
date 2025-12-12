"""优化后的账号业务逻辑服务 - 重构版"""

import json
import csv
import io
from typing import List, Optional, Dict, Any
from fastapi import HTTPException

from database.factory import get_db, begin_tx, commit_tx, rollback_tx
from .repositories.account_repository import AccountRepository
from utils.normalizers import (
    normalize_list,
    normalize_aliases,
    norm_email,
    norm_name,
    norm_birthday,
    norm_email_list,
    norm_phone_digits_list,
    norm_alias_list,
)
from utils.snapshot import fetch_current_state, insert_version_snapshot, get_recovery_maps
from utils.logger import get_logger

logger = get_logger(__name__)


class AccountService:
    """优化后的账号服务

    通过仓储模式分离数据访问和业务逻辑，
    减少重复代码，提高可维护性。
    """

    def __init__(self):
        """初始化服务，不接收 db 连接"""
        self.repo = AccountRepository()

    # ==================== 基础操作 ====================

    def get_account(self, account_id: int) -> Optional[Dict]:
        """获取单个账号"""
        return self.repo.find_by_id(account_id)

    def list_accounts(self, page: int = 1, size: int = 20, **filters) -> Dict[str, Any]:
        """获取账号列表（分页）"""
        query = "SELECT * FROM accounts"
        params = []

        # 构建WHERE子句
        if filters:
            where_clause, where_params = self.repo.build_where_clause(filters)
            query += f" WHERE {where_clause}"
            params.extend(where_params)

        query += " ORDER BY created_at DESC"

        return self.repo.paginate(query, page, size, tuple(params))

    # ==================== 批量操作 ====================

    def batch_create(self, items: List[Dict]) -> Dict[str, Any]:
        """批量创建账号"""
        result = {"success": [], "errors": []}

        for idx, item in enumerate(items):
            try:
                with get_db() as db:
                    begin_tx(db)
                    # 插入主表
                    account_id = self._insert_account(db, item)

                    # 插入辅助信息
                    self._insert_recovery_info(db, account_id, item)

                    # 插入版本快照
                    db.commit()
                    insert_version_snapshot(
                        db,
                        account_id,
                        item.get("note") or "初始导入",
                        item.get("created_by")
                    )

                    result["success"].append({
                        "id": account_id,
                        "email": item["email"]
                    })
                    logger.debug(f"Created account {account_id}: {item['email']}")

            except Exception as e:
                error_msg = str(e)
                result["errors"].append({"index": idx, "error": error_msg})
                logger.error(f"Failed to create account at index {idx}: {error_msg}")

        logger.info(f"Batch create completed: {len(result['success'])} success, {len(result['errors'])} errors")
        return result

    def batch_update(self, items: List[Dict]) -> Dict[str, Any]:
        """批量更新账号"""
        result = {"success": [], "errors": []}

        for idx, item in enumerate(items):
            try:
                account_id = self._resolve_account_id(item)
                if not account_id:
                    result["errors"].append({
                        "index": idx,
                        "error": "Account not found"
                    })
                    continue

                # 获取当前状态
                with get_db() as db:
                    current = self._get_full_account_state(db, account_id)
                if not current:
                    result["errors"].append({
                        "index": idx,
                        "error": "Account not found"
                    })
                    continue

                # 准备更新数据
                update_data = self._prepare_update_data(item, current)

                # 检查是否有变化
                if self._has_no_changes(update_data, current):
                    result["success"].append({
                        "id": account_id,
                        "version": current["version"],
                        "email": current["email"],
                        "no_change": True
                    })
                    continue

                # 执行更新
                with get_db() as db:
                    begin_tx(db)
                    # 更新主表
                    set_clause = ', '.join([f"{k} = ?" for k in update_data.keys()])
                    db.execute(
                        f"UPDATE accounts SET {set_clause} WHERE id = ?",
                        tuple(update_data.values()) + (account_id,)
                    )

                    # 更新子表
                    self._update_recovery_info(db, account_id, item)

                    # 插入版本快照
                    db.commit()
                    insert_version_snapshot(
                        db,
                        account_id,
                        item.get("note") or "更新",
                        item.get("created_by")
                    )

                # 获取新版本
                new_version = self.repo.get_current_version(account_id)
                result["success"].append({
                    "id": account_id,
                    "version": new_version,
                    "email": update_data.get("email", current["email"]),
                    "no_change": False
                })

            except Exception as e:
                error_msg = str(e)
                result["errors"].append({"index": idx, "error": error_msg})
                logger.error(f"Failed to update account at index {idx}: {error_msg}")

        return result

    # ==================== 单个操作 ====================

    def create(self, data: Dict) -> int:
        """创建单个账号"""
        with get_db() as db:
            begin_tx(db)
            account_id = self._insert_account(db, data)
            self._insert_recovery_info(db, account_id, data)
            db.commit()
            insert_version_snapshot(
                db,
                account_id,
                data.get("note") or "创建账号",
                data.get("created_by")
            )
            return account_id

    def update(self, account_id: int, data: Dict) -> bool:
        """更新账号"""
        try:
            # 获取当前状态
            with get_db() as db:
                current = self._get_full_account_state(db, account_id)

            if not current:
                raise HTTPException(404, "Account not found")

            # 准备更新数据
            update_data = self._prepare_update_data(data, current)

            # 执行更新
            with get_db() as db:
                begin_tx(db)
                # 更新主表
                set_clause = ', '.join([f"{k} = ?" for k in update_data.keys()])
                db.execute(
                    f"UPDATE accounts SET {set_clause} WHERE id = ?",
                    tuple(update_data.values()) + (account_id,)
                )
                self._update_recovery_info(db, account_id, data)
                insert_version_snapshot(
                    db,
                    account_id,
                    data.get("note") or "更新账号",
                    data.get("created_by")
                )
                commit_tx(db)

            return True
        except Exception as e:
            logger.error(f"Failed to update account {account_id}: {str(e)}")
            raise

    def update_status(self, account_id: int, status: str) -> bool:
        """更新账号状态"""
        try:
            with get_db() as db:
                # 先检查账号是否存在
                account = self.repo.find_by_id(account_id)
                if not account:
                    return False

                # 插入版本快照（记录状态变更）
                insert_version_snapshot(
                    db,
                    account_id,
                    f"状态变更: {status}",
                    "system"
                )

                # 更新状态
                begin_tx(db)
                db.execute("UPDATE accounts SET status = ? WHERE id = ?", (status, account_id))
                commit_tx(db)
                return True
        except Exception as e:
            logger.error(f"Failed to update status for account {account_id}: {str(e)}")
            return False

    def delete(self, account_id: int) -> bool:
        """删除账号"""
        try:
            with get_db() as db:
                begin_tx(db)
                # 插入版本快照（记录删除）
                insert_version_snapshot(
                    db,
                    account_id,
                    "删除账号",
                    "system"
                )
                # 删除账号
                db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
                commit_tx(db)
                return True
        except Exception as e:
            logger.error(f"Failed to delete account {account_id}: {str(e)}")
            return False

    def restore_version(self, account_id: int, version: int, note: str = None, created_by: str = None) -> bool:
        """恢复账号版本"""
        try:
            with get_db() as db:
                # 获取版本快照
                snapshot = self._get_version_snapshot(db, account_id, version)
                if not snapshot:
                    return False

                # 插入版本快照（记录恢复）
                insert_version_snapshot(
                    db,
                    account_id,
                    note or f"恢复到版本 {version}",
                    created_by
                )

                # 恢复数据
                emails_snapshot = json.loads(snapshot["emails_snapshot_json"])
                recovery_map = get_recovery_maps(emails_snapshot)

                begin_tx(db)
                # 更新主表
                db.execute(
                    """UPDATE accounts SET email = ?, status = ?, username = ?, birthday = ? WHERE id = ?""",
                    (
                        recovery_map["primary_email"],
                        snapshot["status"],
                        recovery_map["username"],
                        recovery_map["birthday"],
                        account_id
                    )
                )

                # 更新辅助信息表
                self._update_recovery_info_from_snapshot(db, account_id, recovery_map)
                commit_tx(db)

                return True
        except Exception as e:
            logger.error(f"Failed to restore version {version} for account {account_id}: {str(e)}")
            return False

    # ==================== 查询操作 ====================

    def get_history_by_account_id(self, account_id: int, page: int = 1, size: int = 20) -> Dict[str, Any]:
        """获取账号历史版本"""
        query = """
            SELECT av.*, (
                SELECT COUNT(*) FROM account_version av2
                WHERE av2.account_id = av.account_id
            ) as total
            FROM account_version av
            WHERE av.account_id = ?
            ORDER BY av.version DESC
        """

        with get_db() as db:
            # 获取总数
            total = db.execute(
                "SELECT COUNT(*) FROM account_version WHERE account_id = ?",
                (account_id,)
            ).fetchone()[0]

            # 获取分页数据
            offset = (page - 1) * size
            rows = db.execute(query + " LIMIT ? OFFSET ?", (account_id, size, offset)).fetchall()

        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size
        }

    def get_history_by_group_id(self, group_id: str, page: int = 1, size: int = 20) -> Dict[str, Any]:
        """获取组的历史版本"""
        query = """
            SELECT av.*, a.email as current_email
            FROM account_version av
            JOIN accounts a ON av.account_id = a.id
            WHERE a.group_id = ?
            ORDER BY av.account_id, av.version DESC
        """

        with get_db() as db:
            # 获取总数
            total = db.execute("""
                SELECT COUNT(*)
                FROM account_version av
                JOIN accounts a ON av.account_id = a.id
                WHERE a.group_id = ?
            """, (group_id,)).fetchone()[0]

            # 获取分页数据
            offset = (page - 1) * size
            rows = db.execute(query + " LIMIT ? OFFSET ?", (group_id, size, offset)).fetchall()

        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size
        }

    # ==================== 导出功能 ====================

    def export_to_csv(self, **filters) -> str:
        """导出账号为CSV"""
        with get_db() as db:
            query = "SELECT * FROM accounts"
            params = []

            # 构建WHERE子句
            if filters:
                where_clause, where_params = self.repo.build_where_clause(filters)
                query += f" WHERE {where_clause}"
                params.extend(where_params)

            query += " ORDER BY created_at DESC"

            # 执行查询
            cursor = db.execute(query, params)
            rows = cursor.fetchall()

            # 生成CSV
            output = io.StringIO()
            writer = csv.writer(output)

            # 写入标题
            if rows:
                writer.writerow(rows[0].keys())

                # 写入数据
                for row in rows:
                    writer.writerow(row.values())

            return output.getvalue()

    # ==================== 私有辅助方法 ====================

    def _insert_account(self, db, item: Dict) -> int:
        """插入账号数据"""
        cursor = db.execute("""
            INSERT INTO accounts (
                email, password, status, username, birthday,
                group_id, aliases, note,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (
            norm_email(item["email"]),
            item["password"],
            item["status"],
            norm_name(item.get("username")),
            norm_birthday(item.get("birthday")),
            item.get("group_id"),
            json.dumps(norm_alias_list(item.get("aliases", []))),
            item.get("note")
        ))
        return cursor.lastrowid

    def _insert_recovery_info(self, db, account_id: int, item: Dict):
        """插入辅助信息"""
        # 插入恢复邮箱
        recovery_email = norm_email(item.get("recovery_email"))
        if recovery_email:
            db.execute(
                "INSERT OR IGNORE INTO account_recovery (account_id, recovery_email) VALUES (?, ?)",
                (account_id, recovery_email)
            )

        # 插入恢复手机
        recovery_phones = norm_phone_digits_list(item.get("recovery_phone"))
        if recovery_phones:
            for phone in recovery_phones:
                db.execute(
                    "INSERT OR IGNORE INTO account_recovery_phone (account_id, recovery_phone) VALUES (?, ?)",
                    (account_id, phone)
                )

    def _update_recovery_info(self, db, account_id: int, item: Dict):
        """更新辅助信息"""
        # 删除旧的恢复信息
        db.execute("DELETE FROM account_recovery WHERE account_id = ?", (account_id,))
        db.execute("DELETE FROM account_recovery_phone WHERE account_id = ?", (account_id,))

        # 插入新的恢复信息
        self._insert_recovery_info(db, account_id, item)

    def _update_recovery_info_from_snapshot(self, db, account_id: int, recovery_map: Dict):
        """从快照恢复辅助信息"""
        # 删除旧的恢复信息
        db.execute("DELETE FROM account_recovery WHERE account_id = ?", (account_id,))
        db.execute("DELETE FROM account_recovery_phone WHERE account_id = ?", (account_id,))

        # 插入恢复信息
        if recovery_map.get("recovery_email"):
            db.execute(
                "INSERT OR IGNORE INTO account_recovery (account_id, recovery_email) VALUES (?, ?)",
                (account_id, recovery_map["recovery_email"])
            )

        if recovery_map.get("recovery_phones"):
            for phone in recovery_map["recovery_phones"]:
                db.execute(
                    "INSERT OR IGNORE INTO account_recovery_phone (account_id, recovery_phone) VALUES (?, ?)",
                    (account_id, phone)
                )

    def _get_full_account_state(self, db, account_id: int) -> Optional[Dict]:
        """获取账号的完整状态"""
        # 获取账号基本信息
        account = self.repo.find_by_id(account_id)
        if not account:
            return None

        # 获取恢复信息
        recovery = db.execute("""
            SELECT
                ar.recovery_email,
                GROUP_CONCAT(arp.recovery_phone) as recovery_phones
            FROM accounts a
            LEFT JOIN account_recovery ar ON a.id = ar.account_id
            LEFT JOIN account_recovery_phone arp ON a.id = arp.account_id
            WHERE a.id = ?
            GROUP BY a.id, ar.recovery_email
        """, (account_id,)).fetchone()

        # 获取当前版本
        current_version = self.repo.get_current_version(account_id)

        return {
            **dict(account),
            "recovery_email": recovery["recovery_email"] if recovery else None,
            "recovery_phones": recovery["recovery_phones"].split(",") if recovery and recovery["recovery_phones"] else [],
            "version": current_version
        }

    def _get_version_snapshot(self, db, account_id: int, version: int) -> Optional[Dict]:
        """获取特定版本的快照"""
        return db.execute(
            "SELECT * FROM account_version WHERE account_id = ? AND version = ?",
            (account_id, version)
        ).fetchone()

    def _resolve_account_id(self, item: Dict) -> Optional[int]:
        """解析账号ID"""
        if "id" in item and item["id"]:
            return item["id"]
        elif "email" in item:
            account = self.repo.find_by_email(item["email"])
            return account["id"] if account else None
        return None

    def _prepare_update_data(self, item: Dict, current: Dict) -> Dict:
        """准备更新数据"""
        update_data = {}

        # 只更新有变化的字段
        if "email" in item and norm_email(item["email"]) != current["email"]:
            update_data["email"] = norm_email(item["email"])

        if "password" in item and item["password"]:
            update_data["password"] = item["password"]

        if "status" in item and item["status"] != current["status"]:
            update_data["status"] = item["status"]

        if "username" in item and norm_name(item["username"]) != current["username"]:
            update_data["username"] = norm_name(item["username"])

        if "birthday" in item and norm_birthday(item["birthday"]) != current["birthday"]:
            update_data["birthday"] = norm_birthday(item["birthday"])

        if "group_id" in item and item["group_id"] != current["group_id"]:
            update_data["group_id"] = item["group_id"]

        if "aliases" in item:
            new_aliases = norm_alias_list(item["aliases"])
            current_aliases = json.loads(current["aliases"] or "[]")
            if new_aliases != current_aliases:
                update_data["aliases"] = json.dumps(new_aliases)

        if "note" in item:
            update_data["note"] = item["note"]

        # 总是更新时间戳
        update_data["updated_at"] = "datetime('now')"

        return update_data

    def _has_no_changes(self, update_data: Dict, current: Dict) -> bool:
        """检查是否有变化"""
        # 移除时间戳字段，因为它总是会变化
        update_data = {k: v for k, v in update_data.items() if k != "updated_at"}
        return len(update_data) == 0