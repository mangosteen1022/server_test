"""时间工具"""

from datetime import datetime, timezone, timedelta


def utc_now() -> str:
    """返回当前UTC时间(标准格式)"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_days_ago(days: int) -> str:
    """返回N天前的UTC时间"""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
