"""邮箱认证 API 路由 - 分离版"""

from typing import Dict, Any
from fastapi import APIRouter, Depends
from models.oauth import GroupLoginRequest, GroupSyncRequest
from services.oauth_service import OAuthService
from routes.auth import get_current_user

router = APIRouter()

# --- 提交接口 ---

@router.post("/auth/login/groups")
async def submit_group_login(
    request: GroupLoginRequest,
    current_user: dict = Depends(get_current_user)
):
    service = OAuthService()
    count = 0
    for group_id in request.group_ids:
        if service.submit_group_login(
            group_id=group_id,
            user_id=current_user["id"],
            role=current_user["role"],
            force_relogin=request.force_relogin
        ):
            count += 1
    return {"success": True, "submitted_count": count, "message": "登录任务已提交"}

@router.post("/auth/sync/groups")
async def submit_group_sync(
    request: GroupSyncRequest,
    current_user: dict = Depends(get_current_user)
):
    service = OAuthService()
    count = 0
    for group_id in request.group_ids:
        if service.submit_sync(
            group_id=group_id,
            user_id=current_user["id"],
            role=current_user["role"],
            strategy=request.strategy
        ):
            count += 1
    return {"success": True, "submitted_count": count, "message": "同步任务已提交"}

# --- 看板接口 (分离) ---

@router.get("/auth/login/status/list")
async def get_login_tasks_status(current_user: dict = Depends(get_current_user)):
    """获取所有活跃的登录任务"""
    service = OAuthService()
    statuses = service.get_my_login_tasks(current_user["id"])
    return {"success": True, "tasks": statuses, "count": len(statuses)}

@router.get("/auth/sync/status/list")
async def get_sync_tasks_status(current_user: dict = Depends(get_current_user)):
    """获取所有活跃的同步任务"""
    service = OAuthService()
    statuses = service.get_my_sync_tasks(current_user["id"])
    return {"success": True, "tasks": statuses, "count": len(statuses)}


@router.delete("/auth/login/groups/{group_id}")
async def cancel_group_login(
    group_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    取消单个登录任务
    前端逻辑: 用户点击登录任务列表中的"取消"按钮时调用
    """
    service = OAuthService()
    # 明确指定 task_type="login"
    cancelled = service.cancel_task_by_type(
        group_id=group_id,
        user_id=current_user["id"],
        task_type="login"
    )
    return {"success": True, "cancelled": cancelled, "message": "登录任务已取消"}

@router.delete("/auth/sync/groups/{group_id}")
async def cancel_group_sync(
    group_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    取消单个同步任务
    前端逻辑: 用户点击同步任务列表中的"取消"按钮时调用
    """
    service = OAuthService()
    # 明确指定 task_type="sync"
    cancelled = service.cancel_task_by_type(
        group_id=group_id,
        user_id=current_user["id"],
        task_type="sync"
    )
    return {"success": True, "cancelled": cancelled, "message": "同步任务已取消"}