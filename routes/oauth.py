"""邮箱认证 API 路由 - 基于group_id的重构版本"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel

from services.oauth_service import AuthService

router = APIRouter()


# ==================== 请求/响应模型 ====================

class GroupLoginRequest(BaseModel):
    """组登录请求"""
    group_ids: List[str]  # group_id列表
    force_relogin: bool = False  # 是否强制重新登录
    auto_sync: bool = True  # 登录成功后是否自动同步


class AccountIdsLoginRequest(BaseModel):
    """账号ID登录请求"""
    account_ids: List[int]  # account_id列表（会自动按group_id分组）
    force_relogin: bool = False
    auto_sync: bool = True


class GroupSyncRequest(BaseModel):
    """组邮件同步请求"""
    group_ids: List[str]  # group_id列表
    strategy: str = "auto"  # "auto", "full", "incremental", "recent"
    days: Optional[int] = 30  # 仅用于 "recent" 策略
    start_date: Optional[str] = None  # 用于时间范围查询
    end_date: Optional[str] = None


class AccountIdsSyncRequest(BaseModel):
    """账号ID邮件同步请求"""
    account_ids: List[int]  # account_id列表（会自动按group_id分组）
    strategy: str = "auto"
    days: Optional[int] = 30
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    task_key: str
    task_type: str
    status: str
    created_at: str
    updated_at: Optional[str]
    result: Optional[Dict] = None
    message: Optional[str] = None


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
    service = AuthService()

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


@router.post("/auth/login/account-ids", response_model=Dict[str, Any])
async def submit_login_by_account_ids(
    request: AccountIdsLoginRequest,
):
    """
    通过账号ID提交登录任务（自动按组分组）

    - 将账号ID按group_id分组
    - 为每个组提交一个登录任务
    - 避免同一组的重复登录
    """
    service = AuthService()

    task_ids = service.submit_group_login_by_account_ids(
        account_ids=request.account_ids,
        auto_sync=request.auto_sync
    )

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
    service = AuthService()
    status = service.get_login_task_status(task_id)

    if not status:
        raise HTTPException(404, "任务不存在或已过期")

    return status


@router.delete("/auth/login/groups/{group_id}")
async def cancel_group_login(
    group_id: str,
):
    """取消邮箱组登录任务"""
    service = AuthService()

    cancelled = service.cancel_group_login(group_id)

    return {
        "success": True,
        "cancelled": cancelled,
        "message": f"组 {group_id} 的登录任务{'已取消' if cancelled else '不存在或无法取消'}"
    }


@router.delete("/auth/login/account-ids/{account_id}")
async def cancel_login_by_account_id(
    account_id: int,
):
    """通过账号ID取消登录任务"""
    service = AuthService()

    cancelled = service.cancel_group_login_by_account_id(account_id)

    return {
        "success": True,
        "cancelled": cancelled,
        "message": f"账号 {account_id} 所属组的登录任务{'已取消' if cancelled else '不存在或无法取消'}"
    }


@router.get("/auth/login/tasks", response_model=List[TaskStatusResponse])
async def list_login_tasks(
    ):
    """列出所有登录任务"""
    service = AuthService()
    return service.list_login_tasks()


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
    service = AuthService()

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


@router.post("/auth/sync/account-ids", response_model=Dict[str, Any])
async def submit_sync_by_account_ids(
    request: AccountIdsSyncRequest,
):
    """
    通过账号ID提交邮件同步任务（自动按组分组）

    - 将账号ID按group_id分组
    - 为每个组提交一个同步任务
    - 避免同一组的重复同步
    """
    service = AuthService()

    task_ids = service.submit_group_sync_by_account_ids(
        account_ids=request.account_ids,
        strategy=request.strategy
    )

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
    service = AuthService()
    status = service.get_sync_task_status(task_id)

    if not status:
        raise HTTPException(404, "任务不存在或已过期")

    return status


@router.delete("/auth/sync/groups/{group_id}")
async def cancel_group_sync(
    group_id: str,
):
    """取消邮箱组同步任务"""
    service = AuthService()

    cancelled = service.cancel_group_sync(group_id)

    return {
        "success": True,
        "cancelled": cancelled,
        "message": f"组 {group_id} 的同步任务{'已取消' if cancelled else '不存在或无法取消'}"
    }


@router.delete("/auth/sync/account-ids/{account_id}")
async def cancel_sync_by_account_id(
    account_id: int,
):
    """通过账号ID取消同步任务"""
    service = AuthService()

    cancelled = service.cancel_group_sync_by_account_id(account_id)

    return {
        "success": True,
        "cancelled": cancelled,
        "message": f"账号 {account_id} 所属组的同步任务{'已取消' if cancelled else '不存在或无法取消'}"
    }


@router.get("/auth/sync/tasks", response_model=List[TaskStatusResponse])
async def list_sync_tasks(
    ):
    """列出所有同步任务"""
    service = AuthService()
    return service.list_sync_tasks()


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
    service = AuthService()

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
    service = AuthService()

    result = service.sync_all_accounts(strategy=strategy)

    return result


# ==================== Token管理路由 ====================

@router.post("/auth/token/verify/{group_id}")
async def verify_group_token(
    group_id: str,
):
    """验证邮箱组的token"""
    service = AuthService()

    result = service.verify_group_token(group_id)

    return result


@router.get("/auth/token/info/{group_id}")
async def get_group_token_info(
    group_id: str,
):
    """获取邮箱组的token信息"""
    service = AuthService()

    result = service.get_group_token_info(group_id)

    if not result.get("valid"):
        raise HTTPException(404, result.get("error", "Token信息不存在"))

    return result


@router.delete("/auth/token/revoke/{group_id}")
async def revoke_group_token(
    group_id: str,
):
    """撤销邮箱组的token"""
    service = AuthService()

    success = service.revoke_group_token(group_id)

    return {
        "success": success,
        "message": f"组 {group_id} 的token{'已撤销' if success else '撤销失败'}"
    }


@router.get("/auth/token/caches", response_model=List[Dict])
async def get_all_token_caches(
    ):
    """获取所有token缓存信息"""
    service = AuthService()

    return service.get_all_token_caches()