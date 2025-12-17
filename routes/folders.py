"""邮件文件夹管理路由"""

import sqlite3
from typing import List, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Body

from database.factory import get_db

router = APIRouter()


@router.get("/accounts/{account_id}/folders")
def get_account_folders(
    account_id: int,
    db: sqlite3.Connection = Depends(get_db),
):
    """获取账号的邮件文件夹列表"""
    r = db.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not r:
        raise HTTPException(404, "account not found")

    rows = db.execute(
        """
        SELECT
            f.id,
            f.display_name,
            f.well_known_name,
            f.parent_folder_id,
            COUNT(m.id) as mail_count,
            SUM(CASE WHEN m.flags = 1 THEN 1 ELSE 0 END) as unread_count
        FROM mail_folder f
        LEFT JOIN mail_message m ON m.folder_id = f.id AND m.account_id = f.account_id
        WHERE f.account_id = ?
        GROUP BY f.id, f.display_name, f.well_known_name, f.parent_folder_id
        ORDER BY
            CASE f.well_known_name
                WHEN 'inbox' THEN 1
                WHEN 'sent' THEN 2
                WHEN 'drafts' THEN 3
                WHEN 'deleted' THEN 4
                WHEN 'junk' THEN 5
                WHEN 'archive' THEN 6
                ELSE 99
            END,
            f.display_name
        """,
        (account_id,),
    ).fetchall()

    return {"items": [dict(r) for r in rows]}


@router.post("/accounts/{account_id}/folders/sync")
def sync_account_folders(account_id: int, folders: List[Dict] = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """同步文件夹信息（从 Graph API 获取后批量保存）"""
    r = db.execute("SELECT id FROM account WHERE id=?", (account_id,)).fetchone()
    if not r:
        raise HTTPException(404, "account not found")

    # 标准文件夹映射
    well_known_map = {
        "inbox": "inbox",
        "sent items": "sent",
        "sentitems": "sent",
        "drafts": "drafts",
        "deleted items": "deleted",
        "deleteditems": "deleted",
        "junk email": "junk",
        "junkemail": "junk",
        "archive": "archive",
        "outbox": "outbox",
        "收件箱": "inbox",
        "已发送邮件": "sent",
        "已发送": "sent",
        "草稿箱": "drafts",
        "草稿": "drafts",
        "已删除邮件": "deleted",
        "已删除": "deleted",
        "垃圾邮件": "junk",
        "存档": "archive",
        "发件箱": "outbox",
    }

    try:
        from ..database import begin_tx, commit_tx, rollback_tx

        begin_tx(db)

        synced_count = 0
        for folder in folders:
            folder_id = folder.get("id")
            if not folder_id:
                continue

            display_name = folder.get("displayName", "")
            display_lower = display_name.lower()

            # 确定 well_known_name
            well_known = None
            for key, value in well_known_map.items():
                if key in display_lower:
                    well_known = value
                    break

            # 插入或更新
            db.execute(
                """
                INSERT INTO mail_folder (id, account_id, display_name, well_known_name, parent_folder_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id, account_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    well_known_name = excluded.well_known_name,
                    parent_folder_id = excluded.parent_folder_id
                """,
                (
                    folder_id,
                    account_id,
                    display_name,
                    well_known,
                    folder.get("parentFolderId"),
                ),
            )
            synced_count += 1

        commit_tx(db)
        return {"success": True, "synced": synced_count}

    except Exception as e:
        rollback_tx(db)
        raise HTTPException(500, f"同步文件夹失败: {str(e)}")


@router.get("/folders/resolve")
def resolve_folder_names(
    account_id: int = Query(...),
    folder_ids: str = Query(..., description="逗号分隔的文件夹ID列表"),
    db: sqlite3.Connection = Depends(get_db),
):
    """批量解析文件夹ID到名称"""
    ids = [fid.strip() for fid in folder_ids.split(",") if fid.strip()]

    if not ids:
        return {}

    placeholders = ",".join(["?"] * len(ids))
    rows = db.execute(
        f"""
        SELECT id, well_known_name, display_name
        FROM mail_folder
        WHERE account_id = ? AND id IN ({placeholders})
        """,
        [account_id] + ids,
    ).fetchall()

    result = {}
    for row in rows:
        name = row["well_known_name"] or row["display_name"]
        result[row["id"]] = name

    return result
