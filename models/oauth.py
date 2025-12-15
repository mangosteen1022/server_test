from typing import List, Optional, Dict
from pydantic import BaseModel, Field


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