"""账号相关 Pydantic 模型"""

from typing import List, Optional, Any, Dict, Literal
from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    """创建账号"""

    email: str
    group_id: str
    password: str
    status: str = "未登录"
    username: Optional[str] = None
    birthday: Optional[str] = None
    recovery_emails: List[str] = Field(default_factory=list)
    recovery_phones: List[str] = Field(default_factory=list)
    note: Optional[str] = "初始导入"
    created_by: Optional[str] = None


class AccountUpdate(BaseModel):
    """更新账号"""

    id: Optional[int] = None
    lookup_email: Optional[str] = None
    email: Optional[str] = None
    group_id: Optional[str] = None
    password: Optional[str] = None
    status: Optional[str] = None
    username: Optional[str] = None
    birthday: Optional[str] = None
    recovery_emails: Optional[List[str]] = None
    recovery_phones: Optional[List[str]] = None
    note: Optional[str] = "更新"
    is_delete: Optional[int] = None
    created_by: Optional[str] = None


class StatusIn(BaseModel):
    """更新状态"""

    status: Literal["未登录", "登录成功", "登录失败", "密码错误", "手机验证"]


class RestoreBody(BaseModel):
    """恢复版本"""

    version: int
    note: Optional[str] = None
    created_by: Optional[str] = None


class BatchResult(BaseModel):
    """批量操作结果"""

    success: List[Any]
    errors: List[Dict[str, Any]]


class TokenCacheSet(BaseModel):
    """Token缓存设置"""

    uuid: str
