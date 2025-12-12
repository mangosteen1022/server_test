"""邮件管理路由"""

import traceback
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, HTTPException, Query, Body

from models.mail import (
    MailBodyIn,
    MailMessageCreate,
    MailMessageUpdate,
    AttachmentAdd,
    MailSearchRequest,
    MailMessageBatchCreate,
)
from services.mail_service import MailService
from utils.time_utils import utc_now
import settings

router = APIRouter()


@router.post("/messages")
def create_mail_message(it: MailMessageCreate):
    """创建邮件消息"""
    service = MailService()
    return service.create_message(it)


@router.patch("/{message_id}")
def update_mail_message(message_id: int, body: MailMessageUpdate):
    """更新邮件消息"""
    service = MailService()
    return service.update_message(message_id, body)


@router.delete("/{message_id}")
def delete_mail_message(message_id: int):
    """删除邮件消息"""
    service = MailService()
    return service.delete_message(message_id)


@router.get("/{message_id}")
def get_mail_detail(message_id: int):
    """获取邮件详情"""
    service = MailService()
    return service.get_detail(message_id)


@router.get("/{message_id}/preview")
def get_mail_preview(message_id: int):
    """获取邮件预览（用于右侧显示）"""
    service = MailService()
    return service.get_preview(message_id)


@router.put("/{message_id}/body")
def update_mail_body(message_id: int, body_data: MailBodyIn):
    """更新或插入邮件正文"""
    service = MailService()
    return service.update_body(message_id, body_data)


@router.post("/{message_id}/attachments")
def add_attachment(message_id: int, data: AttachmentAdd):
    """添加邮件附件"""
    service = MailService()
    return service.add_attachment(message_id, data.storage_url)


@router.get("/{message_id}/attachments")
def list_attachments(message_id: int):
    """列出邮件附件"""
    service = MailService()
    return service.list_attachments(message_id)


@router.delete("/{message_id}/attachments/{attach_id}")
def delete_attachment(message_id: int, attach_id: int):
    """删除邮件附件"""
    service = MailService()
    return service.delete_attachment(message_id, attach_id)


@router.get("/accounts/{account_id}/mails")
def list_account_mails(
    account_id: int,
    q: Optional[str] = Query(None, description="对 subject/from/to 进行包含匹配"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    folder: Optional[str] = None,
):
    """列出账号邮件"""
    service = MailService()
    return service.list_account_mails(account_id, q, folder, page, size)


@router.post("/search")
def search_mails(req: MailSearchRequest):
    """批量搜索邮件"""
    service = MailService()
    return service.search_mails(req)


@router.get("/sync-state/{group_id}")
def get_mail_sync_state(group_id: str):
    """获取邮件同步状态"""
    from database.factory import get_db
    with get_db() as db:
        row = db.execute("SELECT * FROM mail_sync_state WHERE group_id = ?", (group_id,)).fetchone()

        if row:
            return dict(row)
        else:
            return {}


@router.put("/sync-state/{group_id}")
def update_mail_sync_state(
    group_id: str, state: Dict[str, Any] = Body(...), ):
    """更新邮件同步状态"""
    from database.factory import get_db, begin_tx, commit_tx, rollback_tx

    try:
        # 确保时间格式正确
        last_sync_time = state.get("last_sync_time")
        if last_sync_time and not last_sync_time.endswith("Z"):
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(last_sync_time.replace("Z", "+00:00"))
                last_sync_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except (ValueError, AttributeError):
                last_sync_time = utc_now()

        with get_db() as db:
            begin_tx(db)
            db.execute(
                """
                INSERT INTO mail_sync_state (
                    group_id, last_sync_time, last_msg_uid,
                    delta_link, skip_token, total_synced, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    last_sync_time = excluded.last_sync_time,
                    last_msg_uid = excluded.last_msg_uid,
                    delta_link = excluded.delta_link,
                    skip_token = excluded.skip_token,
                    total_synced = excluded.total_synced,
                    updated_at = excluded.updated_at
                """,
                (
                    group_id,
                    last_sync_time,
                    state.get("last_msg_uid"),
                    state.get("delta_link"),
                    state.get("skip_token"),
                    state.get("total_synced", 0),
                    utc_now(),
                ),
            )
            commit_tx(db)
        return {"success": True}
    except Exception as e:
        raise HTTPException(500, f"更新同步状态失败: {str(e)}")


@router.get("/statistics/{account_id}")
def get_mail_statistics(account_id: int):
    """获取邮件统计信息"""
    from database.factory import get_db
    from utils.time_utils import utc_now, utc_days_ago
    from datetime import datetime, timezone

    with get_db() as db:
        # 总邮件数
        total = db.execute("SELECT COUNT(*) as c FROM mail_message WHERE account_id = ?", (account_id,)).fetchone()["c"]

        # 未读邮件数
        unread = db.execute(
            "SELECT COUNT(*) as c FROM mail_message WHERE account_id = ? AND flags = 1", (account_id,)
        ).fetchone()["c"]

        # 今天的邮件
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_str = today_start.strftime("%Y-%m-%dT%H:%M:%SZ")

        today_count = db.execute(
            "SELECT COUNT(*) as c FROM mail_message WHERE account_id = ? AND received_at >= ?",
            (account_id, today_start_str),
        ).fetchone()["c"]

        # 最近7天的邮件
        seven_days_ago = utc_days_ago(7)
        week_count = db.execute(
            "SELECT COUNT(*) as c FROM mail_message WHERE account_id = ? AND received_at > ?", (account_id, seven_days_ago)
        ).fetchone()["c"]

        # 最新邮件
        latest = db.execute(
            """
            SELECT subject, from_addr, received_at
            FROM mail_message
            WHERE account_id = ?
            ORDER BY received_at DESC
            LIMIT 1
            """,
            (account_id,),
        ).fetchone()

        return {
            "total": total,
            "unread": unread,
            "today": today_count,
            "week": week_count,
            "latest": dict(latest) if latest else None,
        }


@router.post("/accounts/{account_id}/mails/batch")
def batch_create_mails(
    account_id: int,
    batch_data: MailMessageBatchCreate,
    optimized: bool = Query(False, description="是否使用优化版本（适合大批量）"),

):
    """
    批量创建邮件

    Args:
        account_id: 账号ID
        batch_data: 批量邮件数据
        optimized: 是否使用优化版本（推荐500封以上使用）

    Returns:
        批量创建结果统计
    """
    # 验证所有邮件都属于该账号
    for mail in batch_data.mails:
        if mail.account_id != account_id:
            raise HTTPException(400, "邮件账号ID与路径参数不匹配")

    service = MailService()

    if optimized:
        return service.batch_create_messages_optimized(batch_data)
    else:
        return service.batch_create_messages(batch_data)


@router.post("/batch")
def batch_create_mails_multi_account(
    batch_data: MailMessageBatchCreate,
    optimized: bool = Query(False, description="是否使用优化版本（适合大批量）"),
):
    """
    批量创建邮件（支持多账号）

    Args:
        batch_data: 批量邮件数据
        optimized: 是否使用优化版本（推荐500封以上使用）

    Returns:
        批量创建结果统计
    """
    service = MailService()

    if optimized:
        return service.batch_create_messages_optimized(batch_data)
    else:
        return service.batch_create_messages(batch_data)


@router.post("/{message_id}/download")
def download_mail_content(message_id: int):
    """
    下载邮件完整内容（从Microsoft Graph API获取）

    Args:
        message_id: 邮件ID

    Returns:
        下载结果，包含完整的邮件内容
    """
    from database.factory import get_db, begin_tx, commit_tx
    from auth.msal_client import MSALClient

    # 获取邮件基本信息
    with get_db() as db:
        mail = db.execute(
            "SELECT account_id, msg_uid FROM mail_message WHERE id=?", (message_id,)
        ).fetchone()

        if not mail:
            raise HTTPException(404, "邮件不存在")

        account_id = mail["account_id"]
        msg_uid = mail["msg_uid"]

        if not msg_uid:
            raise HTTPException(400, "邮件ID无效，无法从Graph API获取")

        # 获取账号的group_id
        account = db.execute(
            "SELECT group_id FROM accounts WHERE id=?", (account_id,)
        ).fetchone()

        if not account:
            raise HTTPException(404, "账号不存在")

        group_id = account["group_id"]

        # 获取账号的token缓存（使用group_id）
        token_cache_row = db.execute(
            "SELECT uuid FROM account_token_cache WHERE group_id=? LIMIT 1",
            (group_id,)
        ).fetchone()

        if not token_cache_row:
            raise HTTPException(400, "账号未登录或token已过期")

    try:
        # 创建MSAL客户端
        msal_client = MSALClient(
            client_id=settings.MSAL_CLIENT_ID,
            authority=settings.MSAL_AUTHORITY,
            scopes=settings.MSAL_SCOPES,
            token_uuid=token_cache_row["uuid"]
        )

        # 检查token是否有效
        token = msal_client.get_access_token()
        if not token:
            raise HTTPException(400, "账号未登录或token已过期")

        # 从Graph API获取完整邮件
        mail_data = msal_client._graph_request(
            "GET",
            f"me/messages/{msg_uid}",
            params={"$select": "*"}
        )
        # 提取邮件数据
        headers = mail_data.get("internetMessageHeaders", [])
        headers_str = "\n".join([f"{h.get('name', '')}: {h.get('value', '')}" for h in headers])

        body_html = mail_data.get("body", {}).get("content", "")
        body_plain = ""  # 如果需要纯文本，可以从MIME内容解析

        # 更新邮件正文表
        with get_db() as db:
            begin_tx(db)
            db.execute(
                """
                INSERT OR REPLACE INTO mail_body (message_id, headers, body_plain, body_html)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, headers_str, body_plain, body_html)
            )
            commit_tx(db)
        return {
            "success": True,
            "message": "邮件内容下载成功",
            "mail_data": {
                "id": message_id,
                "subject": mail_data.get("subject", ""),
                "from": mail_data.get("from", {}),
                "toRecipients": mail_data.get("toRecipients", []),
                "ccRecipients": mail_data.get("ccRecipients", []),
                "receivedDateTime": mail_data.get("receivedDateTime"),
                "body_html": body_html,
                "body_plain": body_plain,
                "attachments": mail_data.get("attachments", [])
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"下载邮件内容失败: {str(e)}")
