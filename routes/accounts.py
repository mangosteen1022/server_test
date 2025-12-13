"""账号管理路由"""
import time
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Body, Depends
from fastapi.responses import Response

from models.account import AccountCreate, AccountUpdate, StatusIn, RestoreBody, BatchResult
from services.account_service import AccountService
from routes.auth import get_current_user, get_current_admin

router = APIRouter()


@router.post("/batch", response_model=BatchResult)
def batch_create_accounts(
    items: List[AccountCreate],
    admin: dict = Depends(get_current_admin)
):
    """批量创建账号 (管理员)"""
    service = AccountService()
    return service.batch_create(items)


@router.put("/batch", response_model=BatchResult)
def batch_update_accounts(
    items: List[AccountUpdate],
    admin: dict = Depends(get_current_admin)
):
    """批量更新账号 (管理员)"""
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
    note_contains: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
    show_deleted: bool = Query(False, description="是否显示已删除账号"), # 新增：控制是否显示软删除数据
    current_user: dict = Depends(get_current_user)
):
    """获取账号列表"""
    service = AccountService()

    filters = {
        "status": status,
        "email_contains": email_contains,
        "recovery_email_contains": recovery_email_contains,
        "recovery_phone": recovery_phone,
        "note_contains": note_contains,
        "updated_after": updated_after,
        "updated_before": updated_before,
        "is_delete": 1 if show_deleted else 0, # 传递软删除过滤
    }

    return service.list_accounts(current_user, page, size, **filters)


@router.get("/{account_id}")
def get_account(
    account_id: int,
    current_user: dict = Depends(get_current_user)
):
    """获取单个账号"""
    service = AccountService()
    return service.get_account(account_id)


@router.get("/history/{group_id}")
def get_history_by_group_id(
    group_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=500),
    current_user: dict = Depends(get_current_user)
):
    """获取账号历史版本（通过group_id）"""
    service = AccountService()
    return service.get_history_by_group_id(group_id, page, size)


@router.patch("/groups/{group_id}/status")  # 修改路由：按组更新
def update_group_status(
    group_id: str,
    body: StatusIn,
    current_user: dict = Depends(get_current_user)
):
    """更新整组账号状态"""
    service = AccountService()
    # 传递 group_id 进行批量更新
    return service.update_status_by_group(group_id, body.status)


@router.post("/groups/{group_id}/restore") # 修改路由：按组回滚
def restore_group_version(
    group_id: str,
    body: RestoreBody,
    admin: dict = Depends(get_current_admin)
):
    """恢复组的账号版本 (管理员)"""
    service = AccountService()
    return service.restore_version_by_group(group_id, body.version, body.note, admin["name"])

@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    admin: dict = Depends(get_current_admin)
):
    """软删除单个账号 (管理员)"""
    service = AccountService()
    return service.delete(account_id)

@router.delete("/groups/{group_id}") # 新增：删除组接口
def delete_group(
    group_id: str,
    admin: dict = Depends(get_current_admin)
):
    """软删除整组账号 (管理员)"""
    service = AccountService()
    return service.delete_group(group_id)

@router.get("/export")
def export_accounts(
    status: Optional[str] = None,
    email_contains: Optional[str] = None,
    recovery_email_contains: Optional[str] = None,
    recovery_phone: Optional[str] = None,
    # alias_contains 已删除
    note_contains: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
    show_deleted: bool = Query(False),
    current_user: dict = Depends(get_current_user)
):
    """导出账号为CSV"""
    service = AccountService()

    filters = {
        "status": status,
        "email_contains": email_contains,
        "recovery_email_contains": recovery_email_contains,
        "recovery_phone": recovery_phone,
        "note_contains": note_contains,
        "updated_after": updated_after,
        "updated_before": updated_before,
        "is_delete": 1 if show_deleted else 0,
    }

    csv_content = service.export_to_csv(current_user, **filters)

    filename = f"accounts_export_{int(time.time())}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )