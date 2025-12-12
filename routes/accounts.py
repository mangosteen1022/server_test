"""账号管理路由"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import Response

from models.account import AccountCreate, AccountUpdate, StatusIn, RestoreBody, BatchResult
from services.account_service import AccountService

router = APIRouter()


@router.post("/batch", response_model=BatchResult)
def batch_create_accounts(items: List[AccountCreate], ):
    """批量创建账号"""
    service = AccountService()
    return service.batch_create(items)


@router.put("/batch", response_model=BatchResult)
def batch_update_accounts(items: List[AccountUpdate], ):
    """批量更新账号"""
    service = AccountService()
    return service.batch_update(items)


@router.get("")
def list_accounts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=1000),
    status: Optional[str] = None,
    email_contains: Optional[str] = None,
    recovery_email_contains: Optional[str] = None,
    recovery_phone: Optional[str] = None,
    alias_contains: Optional[str] = None,
    note_contains: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
):
    """获取账号列表"""
    service = AccountService()

    filters = {
        "status": status,
        "email_contains": email_contains,
        "recovery_email_contains": recovery_email_contains,
        "recovery_phone": recovery_phone,
        "alias_contains": alias_contains,
        "note_contains": note_contains,
        "updated_after": updated_after,
        "updated_before": updated_before,
    }

    return service.list_accounts(page, size, **filters)


@router.get("/{account_id}")
def get_account(account_id: int, ):
    """获取单个账号"""
    service = AccountService()
    return service.get_account(account_id)


@router.get("/{account_id}/history")
def get_history_by_account_id(
    account_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=500),
):
    """获取账号历史版本（通过account_id）"""
    service = AccountService()
    return service.get_history_by_account_id(account_id, page, size)


@router.get("/history/{group_id}")
def get_history_by_group_id(
    group_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=500),
):
    """获取账号历史版本（通过group_id）"""
    service = AccountService()
    return service.get_history_by_group_id(group_id, page, size)


@router.patch("/{account_id}/status")
def update_account_status(account_id: int, body: StatusIn, ):
    """更新账号状态"""
    service = AccountService()
    return service.update_status(account_id, body.status)


@router.post("/{account_id}/restore")
def restore_version(account_id: int, body: RestoreBody, ):
    """恢复账号版本"""
    service = AccountService()
    return service.restore_version(account_id, body.version, body.note, body.created_by)


@router.delete("/{account_id}")
def delete_account(account_id: int, ):
    """删除账号"""
    service = AccountService()
    return service.delete_account(account_id)


@router.get("/export")
def export_accounts(
    status: Optional[str] = None,
    email_contains: Optional[str] = None,
    recovery_email_contains: Optional[str] = None,
    recovery_phone: Optional[str] = None,
    alias_contains: Optional[str] = None,
    note_contains: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
):
    """导出账号为CSV"""
    service = AccountService()

    filters = {
        "status": status,
        "email_contains": email_contains,
        "recovery_email_contains": recovery_email_contains,
        "recovery_phone": recovery_phone,
        "alias_contains": alias_contains,
        "note_contains": note_contains,
        "updated_after": updated_after,
        "updated_before": updated_before,
    }

    csv_content = service.export_to_csv(**filters)

    filename = f"accounts_export_{int(__import__('time').time())}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
