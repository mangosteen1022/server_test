"""FastAPI 依赖注入"""

from typing import Optional
import sqlite3
import logging

from fastapi import Depends, HTTPException, status
from auth.msal_client import MSALClient
from services.mail_sync import MailSyncManager
from database.factory import get_db
from settings import (
    MSAL_CLIENT_ID,
    MSAL_AUTHORITY,
    MSAL_SCOPES,
    MSAL_REDIRECT_PORT,
    TOKEN_DIR
)

logger = logging.getLogger(__name__)


def get_database() -> sqlite3.Connection:
    """获取数据库连接（依赖注入）"""
    return Depends(get_db)


def get_msal_client(token_uuid: Optional[str] = None) -> MSALClient:
    """获取MSAL客户端实例

    Args:
        token_uuid: Token缓存文件的UUID（可选）

    Returns:
        MSAL客户端实例
    """
    try:
        # 确保token目录存在
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)

        return MSALClient(
            client_id=MSAL_CLIENT_ID,
            authority=MSAL_AUTHORITY,
            scopes=MSAL_SCOPES,
            token_uuid=token_uuid,
            default_port=MSAL_REDIRECT_PORT
        )
    except Exception as e:
        logger.error(f"Failed to create MSAL client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize authentication client"
        )


def get_mail_sync_manager() -> MailSyncManager:
    """获取邮件同步管理器实例

    Returns:
        MailSyncManager实例
    """
    try:
        return MailSyncManager()
    except Exception as e:
        logger.error(f"Failed to create mail sync manager: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize mail sync manager"
        )
