"""Pydantic 模型"""

from .account import AccountCreate, AccountUpdate, StatusIn, RestoreBody, BatchResult
from .mail import MailBodyIn, MailSearchRequest

__all__ = [
    "AccountCreate",
    "AccountUpdate",
    "StatusIn",
    "RestoreBody",
    "BatchResult",
    "MailBodyIn",
    "MailSearchRequest",
]
