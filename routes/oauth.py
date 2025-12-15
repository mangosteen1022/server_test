"""邮箱认证 API 路由 - 基于group_id的重构版本"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from models.oauth import *

from services.oauth_service import OAuthService

router = APIRouter()


# ==================== 登录相关路由 ====================

@router.post("/auth/login/groups", response_model=Dict[str, Any])
async def submit_group_login(
    request: GroupLoginRequest,
):
    """
    提交邮箱组登录任务

    - 基于group_id避免重复任务
    - 任务在后台异步执行
    - 返回每个组的任务ID
    """
    service = OAuthService()

    task_ids = {}
    for group_id in request.group_ids:
        task_id = service.submit_group_login(
            group_id=group_id,
            auto_sync=request.auto_sync
        )
        task_ids[group_id] = task_id

    return {
        "success": True,
        "task_ids": task_ids,
        "total_groups": len(task_ids),
        "message": f"已提交 {len(task_ids)} 个组的登录任务"
    }


@router.get("/auth/login/status/{task_id}", response_model=Dict[str, Any])
async def get_login_task_status(
    task_id: str,
):
    """获取登录任务状态"""
    service = OAuthService()
    status = service.get_login_task_status(task_id)

    if not status:
        raise HTTPException(404, "任务不存在或已过期")

    return status


@router.delete("/auth/login/groups/{group_id}")
async def cancel_group_login(
    group_id: str,
):
    """取消邮箱组登录任务"""
    service = OAuthService()

    cancelled = service.cancel_group_login(group_id)

    return {
        "success": True,
        "cancelled": cancelled,
        "message": f"组 {group_id} 的登录任务{'已取消' if cancelled else '不存在或无法取消'}"
    }


# ==================== 邮件同步相关路由 ====================

@router.post("/auth/sync/groups", response_model=Dict[str, Any])
async def submit_group_sync(
    request: GroupSyncRequest,
):
    """
    提交邮箱组邮件同步任务

    - 基于group_id避免重复任务
    - 任务在后台异步执行
    - 返回每个组的任务ID
    """
    service = OAuthService()

    task_ids = {}
    for group_id in request.group_ids:
        task_id = service.submit_group_sync(
            group_id=group_id,
            strategy=request.strategy
        )
        task_ids[group_id] = task_id

    return {
        "success": True,
        "task_ids": task_ids,
        "total_groups": len(task_ids),
        "message": f"已提交 {len(task_ids)} 个组的邮件同步任务"
    }


@router.get("/auth/sync/status/{task_id}", response_model=Dict[str, Any])
async def get_sync_task_status(
    task_id: str,
):
    """获取同步任务状态"""
    service = OAuthService()
    status = service.get_sync_task_status(task_id)

    if not status:
        raise HTTPException(404, "任务不存在或已过期")

    return status


@router.delete("/auth/sync/groups/{group_id}")
async def cancel_group_sync(
    group_id: str,
):
    """取消邮箱组同步任务"""
    service = OAuthService()

    cancelled = service.cancel_group_sync(group_id)

    return {
        "success": True,
        "cancelled": cancelled,
        "message": f"组 {group_id} 的同步任务{'已取消' if cancelled else '不存在或无法取消'}"
    }


# ==================== 批量操作路由 ====================

@router.post("/auth/sync/selected-accounts", response_model=Dict[str, Any])
async def sync_selected_accounts(
    request: AccountIdsSyncRequest,
):
    """
    同步选中的账号（登录+同步）

    - 先提交登录任务
    - 登录成功后自动提交同步任务
    - 返回所有任务的ID
    """
    service = OAuthService()

    result = service.sync_selected_accounts(
        account_ids=request.account_ids,
        strategy=request.strategy
    )

    return result


@router.post("/auth/sync/all-accounts", response_model=Dict[str, Any])
async def sync_all_accounts(
    strategy: str = "auto",
):
    """同步所有账号"""
    service = OAuthService()

    result = service.sync_all_accounts(strategy=strategy)

    return result