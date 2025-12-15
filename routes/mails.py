"""邮件管理路由"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Body, Depends

from database.factory import get_db
from models.mail import MailSearchRequest,BatchFlagRequest,BatchDownloadRequest
from routes.auth import get_current_user
from services.mail_service import MailService

router = APIRouter()


def _get_group_id_by_message_id(message_id: int) -> str:
    """根据 message_id 反查 group_id"""
    with get_db() as db:
        row = db.execute("SELECT group_id FROM mail_message WHERE id = ?", (message_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Message not found")
        return row["group_id"]


@router.post("/groups/{group_id}/search")
def search_group_mails(
        group_id: str,
        req: MailSearchRequest = Body(...),
        current_user: dict = Depends(get_current_user)  # 必须鉴权
):
    """
    搜索指定组内的邮件 (已修复：传递 current_user 进行鉴权)
    """
    service = MailService()
    return service.search_group_mails(group_id, req, current_user)


@router.post("/search/all")
def search_all_mails(
        req: MailSearchRequest = Body(...),
        project_id: Optional[int] = Query(None, description="可选的项目ID，用于限定搜索范围"),
        current_user: dict = Depends(get_current_user)
):
    """
    全局邮件搜索 (支持项目维度)
    """
    service = MailService()
    return service.search_all_mails(req, current_user, project_id)


@router.post("/groups/{group_id}/flags")
def batch_update_mail_flags(
        group_id: str,
        req: BatchFlagRequest
):
    """批量更新邮件状态 (已读/未读/星标等)"""
    service = MailService()
    count = service.batch_update_flags(group_id, req.message_ids, req.action, req.flag)
    return {"success": True, "updated_count": count}


@router.delete("/{message_id}")
def delete_mail_message(message_id: int):
    """删除邮件消息"""
    service = MailService()
    # 修复：先获取 group_id
    group_id = _get_group_id_by_message_id(message_id)
    success = service.delete_message(group_id, message_id)
    if not success:
        raise HTTPException(500, "Delete failed")
    return {"success": True}


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


@router.get("/{message_id}/attachments")
def list_attachments(message_id: int):
    """列出邮件附件"""
    service = MailService()
    return service.list_attachments(message_id)


@router.post("/{message_id}/download")
def download_mail_content(message_id: int):
    """
    下载邮件完整内容（从Microsoft Graph API获取）
    """

    service = MailService()
    return service.download_mail(message_id)

@router.post("/batch/download")
def batch_download_mail_content(
        req: BatchDownloadRequest,
        current_user: dict = Depends(get_current_user)
):
    """
    [多线程] 批量下载邮件完整内容
    """
    service = MailService()
    result = service.batch_download_content(req.message_ids)
    if not result["success"]:
        if "数据库写入失败" in result.get("message", ""):
            raise HTTPException(500, result["message"])
    return result