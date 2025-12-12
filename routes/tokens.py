"""Token缓存管理路由"""

import sqlite3
from fastapi import APIRouter, Depends, HTTPException

from database.factory import get_db
from models.account import TokenCacheSet

router = APIRouter()


@router.get("/accounts/{account_id}/token-caches")
def get_token_cache(account_id: int, db: sqlite3.Connection = Depends(get_db)):
    """获取token缓存"""
    r = db.execute("SELECT uuid, updated_at FROM account_token_cache WHERE account_id=?", (account_id,)).fetchone()

    return {
        "account_id": account_id,
        "uuid": (r["uuid"] if r else None),
        "updated_at": (r["updated_at"] if r else None),
    }


@router.put("/accounts/{account_id}/token-caches")
def set_token_cache(account_id: int, body: TokenCacheSet, db: sqlite3.Connection = Depends(get_db)):
    """保存token缓存"""
    # 检查账号是否存在
    r = db.execute("SELECT id FROM account WHERE id=?", (account_id,)).fetchone()
    if not r:
        raise HTTPException(404, "account not found")

    val = (body.uuid or "").strip().lower()
    if not val:
        raise HTTPException(422, "uuid 不能为空")

    db.execute(
        """
        INSERT INTO account_token_cache(account_id, uuid, updated_at)
        VALUES (?,?,datetime('now'))
        ON CONFLICT(account_id) DO UPDATE SET
          uuid=excluded.uuid,
          updated_at=datetime('now')
        """,
        (account_id, val),
    )

    return {"account_id": account_id, "uuid": val}


@router.get("/token-caches/{uuid}")
def find_accounts_by_uuid(uuid: str, db: sqlite3.Connection = Depends(get_db)):
    """通过UUID查找账号"""
    rows = db.execute(
        """
        SELECT a.*
        FROM account_token_cache t
                 JOIN account a ON a.id=t.account_id
        WHERE t.uuid = ? COLLATE NOCASE
        """,
        (uuid,),
    ).fetchall()

    return {"items": [dict(r) for r in rows]}
