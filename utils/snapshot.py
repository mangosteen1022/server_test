"""账号版本快照管理"""

import json
import sqlite3
from typing import Dict, List, Optional

from fastapi import HTTPException


def fetch_current_state(db: sqlite3.Connection, account_id: int) -> dict:
    """获取账号当前状态（用于比较变化）"""
    from .normalizers import (
        norm_email,
        norm_name,
        norm_birthday,
        norm_email_list,
        norm_phone_digits_list,
        norm_alias_list,
    )

    a = db.execute(
        "SELECT id,email,password,status,username,birthday,version,group_id FROM accounts WHERE id=?", (account_id,)
    ).fetchone()

    if not a:
        raise HTTPException(404, "account not found")

    # 获取该组的所有邮箱（主邮箱+别名邮箱）
    all_emails = [
        r["email"]
        for r in db.execute("SELECT email FROM accounts WHERE group_id=? ORDER BY email", (a["group_id"],))
    ]

    # 获取恢复邮箱
    rec_emails = [
        r["email"]
        for r in db.execute("SELECT email FROM account_recovery_email WHERE group_id=? ORDER BY email", (a["group_id"],))
    ]

    # 获取恢复电话
    rec_phones = [
        r["phone"]
        for r in db.execute("SELECT phone FROM account_recovery_phone WHERE group_id=? ORDER BY phone", (a["group_id"],))
    ]

    return {
        "id": a["id"],
        "group_id": a["group_id"],
        "email": a["email"],  # 当前账号的邮箱
        "all_emails": all_emails,  # 该组的所有邮箱
        "email_norm": norm_email(a["email"]),
        "password": a["password"],
        "status": a["status"],
        "username": a["username"],
        "username_norm": norm_name(a["username"]),
        "birthday": a["birthday"],
        "birthday_norm": norm_birthday(a["birthday"]),
        "version": a["version"],
        "rec_emails": rec_emails,
        "rec_emails_norm": norm_email_list(rec_emails),
        "rec_phones": rec_phones,
        "rec_phones_norm": norm_phone_digits_list(rec_phones),
    }


def insert_version_snapshot(db: sqlite3.Connection, account_id: int, note: Optional[str], who: Optional[str]):
    """插入版本快照到 account_version 表"""
    a = db.execute(
        "SELECT id, email, password, status, username, birthday, version, group_id FROM accounts WHERE id=?", (account_id,)
    ).fetchone()

    if not a:
        raise HTTPException(404, f"account {account_id} not found when snapshot")

    # 获取该组的所有邮箱（主邮箱+别名邮箱）
    all_emails = [
        r["email"]
        for r in db.execute("SELECT email FROM accounts WHERE group_id=? ORDER BY email", (a["group_id"],))
    ]

    # 获取恢复邮箱
    rec_emails = [
        r["email"]
        for r in db.execute("SELECT email FROM account_recovery_email WHERE group_id=? ORDER BY email", (a["group_id"],))
    ]

    # 获取恢复电话
    rec_phones = [
        r["phone"]
        for r in db.execute("SELECT phone FROM account_recovery_phone WHERE group_id=? ORDER BY phone", (a["group_id"],))
    ]

    db.execute(
        """
        INSERT INTO account_version(
            group_id, version, emails_snapshot_json, password, status, username, birthday,
            recovery_emails_json, recovery_phones_json, note, created_by
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            a["group_id"],
            a["version"],
            json.dumps(all_emails, ensure_ascii=False),  # 该组的所有邮箱（主邮箱+别名）
            a["password"],
            a["status"],
            a["username"],
            a["birthday"],
            json.dumps(rec_emails, ensure_ascii=False),  # 恢复邮箱
            json.dumps(rec_phones, ensure_ascii=False),  # 恢复电话
            note,
            who,
        ),
    )


def get_recovery_maps(db: sqlite3.Connection, ids: List[int]):
    """获取辅助信息映射（批量查询优化）"""
    emails_map = {i: [] for i in ids}
    phones_map = {i: [] for i in ids}

    if not ids:
        return emails_map, phones_map

    # 先获取所有账号的 group_id
    group_id_map = {}
    for row in db.execute(f"SELECT id, group_id FROM accounts WHERE id IN ({','.join(['?']*len(ids))})", ids):
        group_id_map[row["id"]] = row["group_id"]

    # 按 group_id 查询恢复信息
    group_ids = list(set(group_id_map.values()))
    if group_ids:
        qmarks = ",".join(["?"] * len(group_ids))

        # 获取恢复邮箱
        group_email_map = {}
        for row in db.execute(f"SELECT group_id, email FROM account_recovery_email WHERE group_id IN ({qmarks})", group_ids):
            group_email_map.setdefault(row["group_id"], []).append(row["email"])

        # 获取恢复电话
        group_phone_map = {}
        for row in db.execute(f"SELECT group_id, phone FROM account_recovery_phone WHERE group_id IN ({qmarks})", group_ids):
            group_phone_map.setdefault(row["group_id"], []).append(row["phone"])

        # 将 group_id 的信息映射回 account_id
        for account_id, group_id in group_id_map.items():
            emails_map[account_id] = group_email_map.get(group_id, [])
            phones_map[account_id] = group_phone_map.get(group_id, [])

    return emails_map, phones_map
