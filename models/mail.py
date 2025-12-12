"""邮件相关 Pydantic 模型"""

from typing import List, Optional
from pydantic import BaseModel, Field


class MailBodyIn(BaseModel):
    """邮件正文"""

    headers: Optional[str] = None
    body_plain: Optional[str] = None
    body_html: Optional[str] = None


class MailMessageCreate(BaseModel):
    """创建邮件消息"""

    group_id: str
    account_id: int
    subject: str
    from_addr: str
    from_name: Optional[str] = None
    to: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    bcc: List[str] = Field(default_factory=list)
    folder_id: str = ""
    labels: List[str] = Field(default_factory=list)
    sent_at: Optional[str] = None
    received_at: Optional[str] = None
    size_bytes: Optional[int] = None
    flags: int = 0
    snippet: Optional[str] = None
    msg_uid: Optional[str] = None
    msg_id: Optional[str] = None
    body: Optional[MailBodyIn] = None
    attachments: List[str] = Field(default_factory=list)


class MailMessageUpdate(BaseModel):
    """更新邮件消息"""

    folder_id: Optional[str] = None
    labels: Optional[List[str]] = None
    flags: Optional[int] = None
    snippet: Optional[str] = None
    subject: Optional[str] = None
    from_addr: Optional[str] = None
    from_name: Optional[str] = None
    to: Optional[List[str]] = None
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None


class AttachmentAdd(BaseModel):
    """添加附件"""

    storage_url: str


class MailSearchRequest(BaseModel):
    """邮件搜索请求"""

    account_ids: List[int]
    subject: Optional[str] = None
    subject_mode: str = "contains"  # contains/exact
    from_q: Optional[str] = None
    from_mode: str = "contains"
    to_q: Optional[str] = None
    to_mode: str = "contains"
    folder: Optional[str] = None
    labels_contains: Optional[str] = None
    received_after: Optional[str] = None
    received_before: Optional[str] = None
    page: int = 1
    size: int = 50


class MailMessageBatchCreate(BaseModel):
    """批量创建邮件请求模型"""

    mails: List[MailMessageCreate]
    ignore_duplicates: bool = True  # 是否忽略重复邮件


class MailMessage(BaseModel):
    """邮件消息响应模型"""

    id: int
    group_id: str
    account_id: int
    subject: str
    from_addr: str
    from_name: Optional[str] = None
    to_joined: str
    folder: str
    folder_id: Optional[str] = None
    labels_joined: str
    sent_at: Optional[str] = None
    received_at: Optional[str] = None
    size_bytes: Optional[int] = None
    flags: int
    snippet: Optional[str] = None
    created_at: str
    updated_at: str


class MailMessageBatchResult(BaseModel):
    """批量创建邮件结果"""

    total: int  # 总数
    saved: int  # 成功保存数量
    duplicates: int  # 重复数量
    errors: int  # 错误数量
    error_details: Optional[List[dict]] = []  # 错误详情
