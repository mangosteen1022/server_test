"""
services/account_service.py
账号业务逻辑 - 完整重构版
集成权限隔离、组操作、软删除及事务安全
"""
import json
import csv
import io
import uuid
from typing import List, Optional, Dict, Any
from fastapi import HTTPException

from database.factory import get_db, begin_tx, commit_tx
from .repositories.account_repository import AccountRepository
from utils.normalizers import (
    norm_email, norm_name, norm_birthday,
    norm_phone_digits_list
)
from utils.snapshot import insert_version_snapshot
from utils.logger import get_logger

logger = get_logger(__name__)

class AccountService:
    def __init__(self):
        self.repo = AccountRepository()

    def get_account(self, account_id: int) -> Optional[Dict]:
        """获取单个账号详情"""
        return self.repo.find_by_id(account_id)

    def list_accounts(
        self,
        current_user: Optional[Dict],
        page: int = 1,
        size: int = 20,
        **filters
    ) -> Dict[str, Any]:
        """
        获取账号列表
        - 管理员：查看所有数据
        - 普通用户：只能查看分配给自己的账号 (通过 project_assignments 关联)
        """
        params = []
        conditions = []

        # === 1. 构建基础查询与权限隔离 ===
        if current_user and current_user["role"] != "admin":
            # 普通用户：需要 JOIN 分配表进行权限过滤
            # 使用 DISTINCT 避免同一账号在不同项目中分配给同一用户时出现重复
            query = """
                SELECT DISTINCT 
                    a.*, 
                    are.email as recovery_email,
                    (SELECT GROUP_CONCAT(phone) FROM account_recovery_phone WHERE group_id = a.group_id) as recovery_phones
                FROM accounts a
                JOIN project_assignments pa ON a.id = pa.account_id
                LEFT JOIN account_recovery_email are ON a.group_id = are.group_id
            """
            conditions.append("pa.user_id = ?")
            params.append(current_user["id"])
        else:
            # 管理员：查看全量数据
            query = """
                SELECT 
                    a.*, 
                    are.email as recovery_email,
                    (SELECT GROUP_CONCAT(phone) FROM account_recovery_phone WHERE group_id = a.group_id) as recovery_phones
                FROM accounts a
                LEFT JOIN account_recovery_email are ON a.group_id = are.group_id
            """
        # === 2. 构建过滤条件 ===

        # 软删除过滤 (默认为0，即不显示已删除的)
        is_delete = filters.get("is_delete", 0)
        conditions.append("a.is_delete = ?")
        params.append(is_delete)

        # 状态 (精确匹配)
        if filters.get("status"):
            conditions.append("a.status = ?")
            params.append(filters["status"])

        # 邮箱 (模糊匹配)
        if filters.get("email_contains"):
            conditions.append("a.email LIKE ?")
            params.append(f"%{filters['email_contains']}%")

        # 辅助邮箱 (模糊匹配 - 关联表 are)
        if filters.get("recovery_email_contains"):
            conditions.append("are.email LIKE ?")
            params.append(f"%{filters['recovery_email_contains']}%")

        # 辅助电话 (子查询 - 因为是一对多关系)
        if filters.get("recovery_phone"):
            conditions.append("EXISTS(SELECT 1 FROM account_recovery_phone arp WHERE arp.group_id = a.group_id AND arp.phone LIKE ?)")
            params.append(f"%{filters['recovery_phone']}%")

        # 备注 (模糊匹配)
        # 注意：请确保数据库 accounts 表中有 note 列，否则需删除此判断
        if filters.get("note_contains"):
            conditions.append("a.note LIKE ?")
            params.append(f"%{filters['note_contains']}%")

        # 时间范围查询
        if filters.get("updated_after"):
            conditions.append("a.updated_at >= ?")
            params.append(filters["updated_after"])

        if filters.get("updated_before"):
            conditions.append("a.updated_at <= ?")
            params.append(filters["updated_before"])

        # === 3. 组合 SQL ===

        if conditions:
            # 如果 query 中还没有 WHERE (管理员模式的初始 SQL 没有 WHERE)，添加 WHERE
            # 如果已经有了 (普通用户模式有 WHERE pa.user_id=?)，添加 AND
            # 这里统一处理：基础 Query 不带 WHERE，第一个条件加 WHERE，后续加 AND
            # 为了简化逻辑，我们在基础 Query 后手动检查是否已有 WHERE 比较麻烦
            # 这里的策略：我们在条件拼接时统一用 AND 连接，然后拼接到 WHERE 1=1 后面

            # 修正：上面的 query 定义里没有 WHERE 1=1，我们补上
            if "WHERE" not in query:
                query += " WHERE 1=1 "

            query += " AND " + " AND ".join(conditions)

        # 添加排序
        query += " ORDER BY a.created_at DESC"

        # === 4. 执行分页查询 ===
        return self.repo.paginate(query, page, size, tuple(params))

    def batch_create(self, items: List[Dict]) -> Dict[str, Any]:
        """批量创建账号"""
        result = {"success": [], "errors": []}

        with get_db() as db:
            begin_tx(db)
            try:
                for idx, item in enumerate(items):
                    try:
                        email = norm_email(item["email"])
                        # 生成或使用提供的 group_id
                        group_id = item.get("group_id") or str(uuid.uuid4())

                        account_data = {
                            "email": email,
                            "password": item["password"],
                            "status": item.get("status", "未登录"),
                            "group_id": group_id,
                            "username": norm_name(item.get("username")),
                            "birthday": norm_birthday(item.get("birthday")),
                            "note": item.get("note"),
                            # 确保数据库有这些字段
                            "created_at": "datetime('now')",
                            "updated_at": "datetime('now')",
                            "is_delete": 0
                        }

                        # 插入主表 (传入 db 连接)
                        account_id = self.repo.insert(account_data, db=db)

                        # 插入辅助信息
                        self._insert_recovery_info(db, group_id, item)

                        # 创建快照
                        insert_version_snapshot(db, account_id, "初始导入", "admin")

                        result["success"].append({
                            "id": account_id,
                            "email": email,
                            "group_id": group_id
                        })

                    except Exception as inner_e:
                        # 记录单条错误，不中断整个批次
                        result["errors"].append({"index": idx, "error": str(inner_e)})
                        pass

                commit_tx(db)
            except Exception as e:
                db.rollback()
                logger.error(f"Batch create failed transaction: {e}")
                raise HTTPException(500, f"批量导入失败: {str(e)}")

        return result

    def batch_update(self, items: List[Any]) -> Dict[str, Any]:
        """
        批量更新账号 (完整实现)
        支持通过 ID 或 lookup_email 查找账号
        支持更新主表字段及辅助邮箱/电话（按 Group 更新）
        """
        result = {"success": [], "errors": []}

        with get_db() as db:
            begin_tx(db)
            try:
                for idx, item_obj in enumerate(items):
                    try:
                        # 兼容 Pydantic 对象或 Dict
                        item = item_obj.dict(exclude_unset=True) if hasattr(item_obj, "dict") else item_obj

                        # 1. 确定账号ID
                        account_id = item.get("id")
                        if not account_id and item.get("lookup_email"):
                            # 如果没传 ID 但传了查找邮箱，尝试查找
                            acc = self.repo.find_by_email(item["lookup_email"], db=db)
                            if acc:
                                account_id = acc["id"]

                        if not account_id:
                            result["errors"].append({"index": idx, "error": "缺少 account_id 或有效的 lookup_email"})
                            continue

                        # 获取当前账号信息（用于获取当前的 group_id）
                        current_account = self.repo.find_by_id(account_id, db=db)
                        if not current_account:
                            result["errors"].append({"index": idx, "error": f"未找到 ID 为 {account_id} 的账号"})
                            continue

                        current_group_id = current_account["group_id"]

                        # 2. 准备主表更新数据
                        update_data = {}
                        if "email" in item:
                            update_data["email"] = norm_email(item["email"])
                        if "password" in item:
                            update_data["password"] = item["password"]
                        if "status" in item:
                            update_data["status"] = item["status"]
                        if "username" in item:
                            update_data["username"] = norm_name(item["username"])
                        if "birthday" in item:
                            update_data["birthday"] = norm_birthday(item["birthday"])
                        if "note" in item:
                            update_data["note"] = item["note"]
                        if "group_id" in item:
                            update_data["group_id"] = item["group_id"]
                            # 如果修改了 group_id，后续辅助信息的更新需应用到新组
                            current_group_id = item["group_id"]

                        # 总是更新时间戳
                        update_data["updated_at"] = "datetime('now')"

                        # 3. 执行主表更新
                        if update_data:
                            # 剔除不属于 accounts 表的字段 (如 recovery_emails) 再传入 repo
                            # repo.update_fields 内部只处理 SQL update，不负责业务逻辑
                            db_fields = {k: v for k, v in update_data.items() if k in [
                                "email", "password", "status", "username", "birthday",
                                "aliases", "note", "group_id", "updated_at"
                            ]}
                            if db_fields:
                                self.repo.update_fields(account_id, db_fields, db=db)

                        # 4. 更新辅助信息 (基于 Group ID)
                        # 如果请求中包含 recovery_emails/phones，则全量替换该组的辅助信息
                        if "recovery_emails" in item or "recovery_phones" in item:
                            self._update_recovery_info(db, current_group_id, item)

                        # 5. 创建版本快照
                        created_by = item.get("created_by", "batch_update")
                        # 这里的快照会自动读取最新的数据库状态（包括刚才更新的字段）
                        insert_version_snapshot(db, account_id, item.get("note", "批量更新"), created_by)

                        result["success"].append({
                            "id": account_id,
                            "email": update_data.get("email", current_account["email"])
                        })

                    except Exception as inner_e:
                        result["errors"].append({"index": idx, "error": str(inner_e)})
                        # 遇到单条错误继续，不中断整个事务（可选策略）
                        pass

                commit_tx(db)
            except Exception as e:
                db.rollback()
                logger.error(f"Batch update failed: {e}")
                raise HTTPException(500, f"批量更新失败: {str(e)}")

        return result

    def _update_recovery_info(self, db, group_id: str, item: Dict):
        """
        更新辅助信息 (先删除旧的，再插入新的)
        注意：辅助信息是绑定在 group_id 上的，修改一个账号会影响同组所有账号
        """
        # 1. 处理辅助邮箱
        if "recovery_emails" in item:
            # 删除该组所有辅助邮箱
            db.execute("DELETE FROM account_recovery_email WHERE group_id = ?", (group_id,))

            # 插入新的列表
            rec_emails = [norm_email(e) for e in item["recovery_emails"] if e]
            # 去重
            rec_emails = list(set(rec_emails))

            for email in rec_emails:
                db.execute(
                    "INSERT OR IGNORE INTO account_recovery_email (group_id, email) VALUES (?, ?)",
                    (group_id, email)
                )

        # 2. 处理辅助电话
        if "recovery_phones" in item:
            # 删除该组所有辅助电话
            db.execute("DELETE FROM account_recovery_phone WHERE group_id = ?", (group_id,))

            # 规范化并插入新的
            rec_phones = norm_phone_digits_list(item["recovery_phones"])

            for phone in rec_phones:
                db.execute(
                    "INSERT OR IGNORE INTO account_recovery_phone (group_id, phone) VALUES (?, ?)",
                    (group_id, phone)
                )

    def delete(self, account_id: int) -> bool:
        """软删除单个账号"""
        with get_db() as db:
            begin_tx(db)
            try:
                # 1. 软删除
                # 注意：使用 execute_update 时传入 db，避免重复开启事务
                self.repo.execute_update("UPDATE accounts SET is_delete = 1 WHERE id = ?", (account_id,), db=db)

                # 2. 生成快照
                insert_version_snapshot(db, account_id, "单个账号软删除", "admin")

                # 3. 关联数据处理（视业务需求，可能不需要删除 project_assignments）
                # db.execute("DELETE FROM project_assignments WHERE account_id = ?", (account_id,))

                commit_tx(db)
                return True
            except Exception as e:
                db.rollback()
                logger.error(f"Soft delete account failed: {e}")
                return False

    def delete_group(self, group_id: str) -> bool:
        """软删除整组账号"""
        with get_db() as db:
            begin_tx(db)
            try:
                # 1. 软删除整组
                self.repo.execute_update("UPDATE accounts SET is_delete = 1 WHERE group_id = ?", (group_id,), db=db)

                # 2. 生成快照
                # 需要找到该组任意一个账号ID来触发快照生成逻辑（snapshot 工具目前依赖 account_id）
                one_account = db.execute("SELECT id FROM accounts WHERE group_id = ? LIMIT 1", (group_id,)).fetchone()
                if one_account:
                    # 注意：insert_version_snapshot 会读取该组的所有信息并保存
                    insert_version_snapshot(db, one_account["id"], "整组软删除", "admin")

                commit_tx(db)
                return True
            except Exception as e:
                db.rollback()
                logger.error(f"Soft delete group failed: {e}")
                return False

    def update_status_by_group(self, group_id: str, status: str) -> bool:
        """按组更新状态"""
        with get_db() as db:
            begin_tx(db)
            try:
                # 1. 更新状态
                self.repo.execute_update("UPDATE accounts SET status = ? WHERE group_id = ?", (status, group_id), db=db)

                # 2. 生成快照
                one_account = db.execute("SELECT id FROM accounts WHERE group_id = ? LIMIT 1", (group_id,)).fetchone()
                if one_account:
                    insert_version_snapshot(db, one_account["id"], f"组状态变更: {status}", "system")

                commit_tx(db)
                return True
            except Exception as e:
                db.rollback()
                logger.error(f"Update group status failed: {e}")
                return False

    def restore_version_by_group(self, group_id: str, version: int, note: str, created_by: str) -> bool:
        """按组回滚快照"""
        try:
            with get_db() as db:
                # 1. 获取快照
                snapshot = db.execute(
                    "SELECT * FROM account_version WHERE group_id = ? AND version = ?",
                    (group_id, version)
                ).fetchone()

                if not snapshot:
                    return False

                # 2. 插入新快照（记录这次回滚操作）
                one_account = db.execute("SELECT id FROM accounts WHERE group_id = ? LIMIT 1", (group_id,)).fetchone()
                if one_account:
                    insert_version_snapshot(db, one_account["id"], note or f"回滚到版本 {version}", created_by)

                # 3. 恢复核心字段
                # 快照中存储了该组当时所有的状态
                recovery_emails = json.loads(snapshot["recovery_emails_json"])
                recovery_phones = json.loads(snapshot["recovery_phones_json"])

                begin_tx(db)

                # 恢复整组的基础信息
                db.execute(
                    """UPDATE accounts SET password = ?, status = ?, username = ?, birthday = ? WHERE group_id = ?""",
                    (snapshot["password"], snapshot["status"], snapshot["username"], snapshot["birthday"], group_id)
                )

                # 恢复 is_delete 状态 (回滚=复活)
                db.execute("UPDATE accounts SET is_delete = 0 WHERE group_id = ?", (group_id,))

                # 恢复辅助信息 (先删后加)
                db.execute("DELETE FROM account_recovery_email WHERE group_id = ?", (group_id,))
                db.execute("DELETE FROM account_recovery_phone WHERE group_id = ?", (group_id,))

                for email in recovery_emails:
                    db.execute("INSERT INTO account_recovery_email(group_id, email) VALUES(?,?)", (group_id, email))
                for phone in recovery_phones:
                    db.execute("INSERT INTO account_recovery_phone(group_id, phone) VALUES(?,?)", (group_id, phone))

                commit_tx(db)
                return True
        except Exception as e:
            logger.error(f"Restore group version failed: {e}")
            return False

    def get_history_by_group_id(self, group_id: str, page: int = 1, size: int = 20) -> Dict[str, Any]:
        """获取组的历史版本"""
        query = """
            SELECT av.*, 
                   (SELECT COUNT(*) FROM account_version av2 WHERE av2.group_id = av.group_id) as total
            FROM account_version av
            WHERE av.group_id = ?
            ORDER BY av.version DESC
        """
        # 为了兼容 repo.paginate 的简单计数逻辑，这里使用简化查询
        # 如果 repo.paginate 依然无法处理复杂子查询计数，建议直接写 raw sql
        return self.repo.paginate("SELECT * FROM account_version WHERE group_id = ? ORDER BY version DESC", page, size, (group_id,))

    def export_to_csv(self, current_user: Optional[Dict], **filters) -> str:
        """导出 CSV (复用 list_accounts 的权限和筛选逻辑)"""
        # 设置一个足够大的 size 来导出所有匹配数据
        data = self.list_accounts(current_user, page=1, size=100000, **filters)
        items = data["items"]

        output = io.StringIO()
        writer = csv.writer(output)

        if items:
            # 动态定义表头
            headers = ["id", "email", "password", "group_id", "status", "recovery_email", "recovery_phones", "note", "created_at"]
            writer.writerow(headers)
            for item in items:
                # 安全获取字段，防止 Key Error
                row = [str(item.get(h, "")) for h in headers]
                writer.writerow(row)

        return output.getvalue()

    def update_status(self, account_id: int, status: str) -> bool:
        """更新单个账号状态"""
        return self.repo.update_status(account_id, status)

    def _insert_recovery_info(self, db, group_id: str, item: Dict):
        """插入辅助信息 (内部方法，接收 db 连接)"""
        rec_email = norm_email(item.get("recovery_email"))
        if rec_email:
            db.execute(
                "INSERT OR IGNORE INTO account_recovery_email (group_id, email) VALUES (?, ?)",
                (group_id, rec_email)
            )

        rec_phone = item.get("recovery_phone")
        if rec_phone:
            phones = norm_phone_digits_list([rec_phone])
            for p in phones:
                db.execute(
                    "INSERT OR IGNORE INTO account_recovery_phone (group_id, phone) VALUES (?, ?)",
                    (group_id, p)
                )