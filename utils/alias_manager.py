"""别名管理工具"""

import sqlite3
from typing import List, Optional, Tuple
from settings import DB_PATH


class AliasManager:
    """邮箱别名管理器"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_all_groups(self) -> List[dict]:
        """获取所有邮箱组"""
        with self.get_connection() as conn:
            groups = conn.execute("""
                SELECT
                    group_id,
                    GROUP_CONCAT(email, ', ') as emails,
                    COUNT(*) as email_count
                FROM account
                GROUP BY group_id
                HAVING COUNT(*) > 1
                ORDER BY group_id
            """).fetchall()
            return [dict(g) for g in groups]

    def get_group_members(self, group_id: str) -> List[dict]:
        """获取指定组的所有成员"""
        with self.get_connection() as conn:
            members = conn.execute("""
                SELECT * FROM account
                WHERE group_id = ?
                ORDER BY email
            """, (group_id,)).fetchall()
            return [dict(m) for m in members]

    def create_alias_group(self, emails: List[str]) -> Optional[str]:
        """创建别名组（将多个邮箱合并为一个组）"""
        if not emails:
            return None

        with self.get_connection() as conn:
            # 检查邮箱是否存在
            placeholders = ','.join(['?'] * len(emails))
            existing = conn.execute(
                f"SELECT id, email, group_id FROM account WHERE email IN ({placeholders})",
                emails
            ).fetchall()

            if len(existing) != len(emails):
                print(f"警告: 部分邮箱不存在")
                missing = set(emails) - {e['email'] for e in existing}
                print(f"不存在的邮箱: {missing}")
                return None

            # 生成新的 UUID 作为 group_id
            import uuid
            new_group_id = str(uuid.uuid4())

            # 更新所有邮箱到同一个组
            for email in emails:
                conn.execute("""
                    UPDATE account
                    SET group_id = ?, updated_at = datetime('now')
                    WHERE email = ?
                """, (new_group_id, email))

            conn.commit()
            print(f"已创建别名组，group_id={new_group_id}")
            return new_group_id

    def add_alias_to_group(self, primary_email: str, alias_email: str) -> bool:
        """将别名邮箱添加到主邮箱所在组"""
        with self.get_connection() as conn:
            # 获取主邮箱的group_id
            primary = conn.execute(
                "SELECT id, group_id FROM account WHERE email = ?",
                (primary_email,)
            ).fetchone()

            if not primary:
                print(f"错误: 主邮箱 {primary_email} 不存在")
                return False

            # 检查别名邮箱是否存在
            alias = conn.execute(
                "SELECT id, group_id FROM account WHERE email = ?",
                (alias_email,)
            ).fetchone()

            if not alias:
                print(f"错误: 别名邮箱 {alias_email} 不存在")
                return False

            # 更新别名邮箱的group_id
            conn.execute("""
                UPDATE account
                SET group_id = ?, updated_at = datetime('now')
                WHERE email = ?
            """, (primary['group_id'], alias_email))

            conn.commit()
            print(f"已将 {alias_email} 添加到 {primary_email} 的组")
            return True

    def remove_from_group(self, email: str) -> bool:
        """将邮箱从组中移除（成为独立组）"""
        with self.get_connection() as conn:
            account = conn.execute(
                "SELECT id, group_id FROM account WHERE email = ?",
                (email,)
            ).fetchone()

            if not account:
                print(f"错误: 邮箱 {email} 不存在")
                return False

            # 检查是否已经是独立组
            if conn.execute(
                "SELECT COUNT(*) FROM account WHERE group_id = ?",
                (account['group_id'],)
            ).fetchone()[0] == 1:
                print(f"{email} 已经是独立组")
                return True

            # 生成新的 UUID 作为独立组的 group_id
            import uuid
            new_group_id = str(uuid.uuid4())

            # 设置为新的独立组
            conn.execute("""
                UPDATE account
                SET group_id = ?, updated_at = datetime('now')
                WHERE email = ?
            """, (new_group_id, email))

            conn.commit()
            print(f"已将 {email} 设置为独立组，新的 group_id={new_group_id}")
            return True

    def find_account_groups(self, email_pattern: str) -> List[dict]:
        """查找匹配的邮箱及其组信息"""
        with self.get_connection() as conn:
            accounts = conn.execute("""
                SELECT
                    a.id,
                    a.email,
                    a.group_id,
                    g.emails as group_members,
                    g.member_count
                FROM account a
                LEFT JOIN (
                    SELECT
                        group_id,
                        GROUP_CONCAT(email, ', ') as emails,
                        COUNT(*) as member_count
                    FROM account
                    GROUP BY group_id
                ) g ON a.group_id = g.group_id
                WHERE a.email LIKE ?
                ORDER BY a.email
            """, (f"%{email_pattern}%",)).fetchall()
            return [dict(a) for a in accounts]

    def merge_groups(self, group_id1: str, group_id2: str) -> bool:
        """合并两个组"""
        with self.get_connection() as conn:
            # 生成新的 UUID 作为合并后的组 ID
            import uuid
            new_group_id = str(uuid.uuid4())

            # 更新所有成员到新组
            conn.execute("""
                UPDATE account
                SET group_id = ?, updated_at = datetime('now')
                WHERE group_id IN (?, ?)
            """, (new_group_id, group_id1, group_id2))

            conn.commit()
            print(f"已合并组 {group_id1} 和 {group_id2} 到新组 {new_group_id}")
            return True

    def export_groups(self) -> List[Tuple[str, List[str]]]:
        """导出所有组的邮箱"""
        groups = []
        with self.get_connection() as conn:
            result = conn.execute("""
                SELECT group_id, GROUP_CONCAT(email, ',') as emails
                FROM account
                GROUP BY group_id
            """).fetchall()

            for row in result:
                emails = row['emails'].split(',')
                groups.append((f"组{row['group_id']}", emails))

        return groups

    def import_groups(self, groups_data: List[Tuple[str, List[str]]]) -> int:
        """导入组数据"""
        imported = 0
        with self.get_connection() as conn:
            for group_name, emails in groups_data:
                if self.create_alias_group(emails):
                    imported += 1

        print(f"已导入 {imported} 个组")
        return imported


def main():
    """命令行工具"""
    import argparse

    parser = argparse.ArgumentParser(description='邮箱别名管理工具')
    parser.add_argument('command', choices=[
        'list', 'show', 'create', 'add', 'remove', 'find', 'merge', 'export'
    ], help='要执行的命令')
    parser.add_argument('--emails', nargs='+', help='邮箱列表')
    parser.add_argument('--primary', help='主邮箱')
    parser.add_argument('--alias', help='别名邮箱')
    parser.add_argument('--email', help='邮箱地址')
    parser.add_argument('--pattern', help='搜索模式')
    parser.add_argument('--group1', help='组ID1 (UUID)')
    parser.add_argument('--group2', help='组ID2 (UUID)')

    args = parser.parse_args()
    manager = AliasManager()

    if args.command == 'list':
        groups = manager.get_all_groups()
        if not groups:
            print("没有找到别名组")
        else:
            print("\n别名组列表:")
            for group in groups:
                print(f"  {group['group_id']}: {group['emails']}")

    elif args.command == 'show':
        if not args.group1:
            print("错误: 需要提供 --group1")
            return
        members = manager.get_group_members(args.group1)
        print(f"\n组 {args.group1} 的成员:")
        for m in members:
            print(f"  {m['email']} (ID: {m['id']})")

    elif args.command == 'create':
        if not args.emails:
            print("错误: 需要提供 --emails")
            return
        manager.create_alias_group(args.emails)

    elif args.command == 'add':
        if not args.primary or not args.alias:
            print("错误: 需要提供 --primary 和 --alias")
            return
        manager.add_alias_to_group(args.primary, args.alias)

    elif args.command == 'remove':
        if not args.email:
            print("错误: 需要提供 --email")
            return
        manager.remove_from_group(args.email)

    elif args.command == 'find':
        if not args.pattern:
            print("错误: 需要提供 --pattern")
            return
        results = manager.find_account_groups(args.pattern)
        for r in results:
            print(f"\n邮箱: {r['email']}")
            print(f"组ID: {r['group_id']}")
            print(f"组成员: {r['group_members']}")

    elif args.command == 'merge':
        if not args.group1 or not args.group2:
            print("错误: 需要提供 --group1 和 --group2")
            return
        manager.merge_groups(args.group1, args.group2)

    elif args.command == 'export':
        groups = manager.export_groups()
        print("\n导出的组:")
        for name, emails in groups:
            print(f"{name}: {', '.join(emails)}")


if __name__ == '__main__':
    main()