"""邮件相关 Pydantic 模型"""

from typing import List, Optional
from pydantic import BaseModel, Field


class MailBodyIn(BaseModel):
    """邮件正文"""

    headers: Optional[str] = None
    body_plain: Optional[str] = None
    body_html: Optional[str] = None

class BatchFlagRequest(BaseModel):
    message_ids: List[int]
    action: str  # "add" | "remove"
    flag: str    # "Read" | "Flagged"


class BatchDownloadRequest(BaseModel):
    """批量下载请求"""
    message_ids: List[int]


class MailSearchRequest(BaseModel):
    """
    邮件搜索请求参数模型
    (已更新以支持 MailService 的通用搜索逻辑)
    """
    # 关键词搜索 (同时匹配主题、发件人、收件人)
    query: Optional[str] = None

    # 字段定向搜索 (包含匹配) ===
    subject: Optional[str] = None  # 主题包含
    from_addr: Optional[str] = None  # 发件人包含
    to_addr: Optional[str] = None  # 收件人包含

    # 属性精确过滤 ===
    folder_id: Optional[str] = None  # 文件夹ID (精确匹配)

    # 状态布尔过滤 (True/False/None) ===
    has_attachments: Optional[bool] = None  # 是否有附件
    is_unread: Optional[bool] = None  # 是否未读 (True=未读, False=已读)
    is_flagged: Optional[bool] = None  # 是否星标/旗标 (True=有, False=无)

    # 时间范围过滤 ===
    date_from: Optional[str] = None  # 接收时间 >= date_from
    date_to: Optional[str] = None  # 接收时间 <= date_to

    # 分页参数 ===
    page: int = 1
    size: int = 50
