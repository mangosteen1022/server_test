"""Pydantic 模型"""

from .account import AccountCreate, AccountUpdate, StatusIn, RestoreBody, BatchResult
from .mail import MailBodyIn, MailMessageCreate, MailMessageUpdate, AttachmentAdd, MailSearchRequest

__all__ = [
    "AccountCreate",
    "AccountUpdate",
    "StatusIn",
    "RestoreBody",
    "BatchResult",
    "MailBodyIn",
    "MailMessageCreate",
    "MailMessageUpdate",
    "AttachmentAdd",
    "MailSearchRequest",
]
