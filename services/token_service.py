"""Token服务"""

from typing import Dict, Optional, List
from pathlib import Path
import uuid

import settings
from auth.msal_client import MSALClient
from utils.logger import get_logger
from database.factory import get_db

logger = get_logger(__name__)


class TokenService:
    """Token管理服务"""

    def __init__(self):
        """初始化Token服务"""
        pass

    def get_cached_token_uuid(self, group_id: str) -> Optional[str]:
        """获取缓存的token UUID

        Args:
            group_id: 账户组ID

        Returns:
            token UUID 或 None
        """
        try:
            with get_db() as db:
                row = db.execute(
                    "SELECT uuid FROM account_token_cache WHERE group_id=?",
                    (group_id,)
                ).fetchone()
                return row["uuid"] if row else None
        except Exception as e:
            logger.error(f"Failed to get cached token for group {group_id}: {str(e)}")
            return None

    def save_token_cache(self, group_id: str, token_uuid: str) -> bool:
        """保存token缓存到数据库

        Args:
            group_id: 账户组ID
            token_uuid: token UUID

        Returns:
            是否成功
        """
        try:
            with get_db() as db:
                db.execute(
                    """
                    INSERT INTO account_token_cache(group_id, uuid, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(group_id) DO UPDATE SET
                        uuid = excluded.uuid,
                        updated_at = excluded.updated_at
                """,
                    (group_id, token_uuid)
                )
                db.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to save token cache for group {group_id}: {str(e)}")
            return False

    def delete_token_cache(self, group_id: str) -> bool:
        """删除token缓存

        Args:
            group_id: 账户组ID

        Returns:
            是否成功
        """
        try:
            with get_db() as db:
                cursor = db.execute(
                    "DELETE FROM account_token_cache WHERE group_id = ?",
                    (group_id,)
                )
                db.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete token cache for group {group_id}: {str(e)}")
            return False

    def get_all_token_caches(self) -> List[Dict]:
        """获取所有token缓存信息

        Returns:
            token缓存列表
        """
        try:
            with get_db() as db:
                rows = db.execute("""
                    SELECT group_id, uuid, updated_at
                    FROM account_token_cache
                    ORDER BY updated_at DESC
                """).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get all token caches: {str(e)}")
            return []

    def create_msal_client(self, group_id: str, token_uuid: str) -> Optional[MSALClient]:
        """创建MSAL客户端

        Args:
            group_id: 账户组ID
            token_uuid: token UUID

        Returns:
            MSAL客户端实例或None
        """
        try:
            token_path = settings.TOKEN_DIR / f"{token_uuid}.json"
            if not token_path.exists():
                return None

            msal_client = MSALClient(
                client_id=settings.MSAL_CLIENT_ID,
                authority=settings.MSAL_AUTHORITY,
                scopes=settings.MSAL_SCOPES,
                token_uuid=token_uuid
            )

            return msal_client
        except Exception as e:
            logger.error(f"Failed to create MSAL client for group {group_id}: {str(e)}")
            return None

    def verify_token(self, group_id: str) -> Dict:
        """验证token是否有效

        Args:
            group_id: 账户组ID

        Returns:
            验证结果
        """
        token_uuid = self.get_cached_token_uuid(group_id)
        if not token_uuid:
            return {"valid": False, "error": "未找到token缓存"}

        msal_client = self.create_msal_client(group_id, token_uuid)
        if not msal_client:
            return {"valid": False, "error": "无法创建MSAL客户端"}

        try:
            token = msal_client.get_access_token()
            if token:
                # 获取用户信息
                user_info = msal_client.get_user_info()
                return {
                    "valid": True,
                    "token_uuid": token_uuid,
                    "user_info": user_info
                }
            else:
                # Token无效，删除缓存
                self.delete_token_cache(group_id)
                return {"valid": False, "error": "Token无效或已过期"}
        except Exception as e:
            logger.error(f"Failed to verify token for group {group_id}: {str(e)}")
            return {"valid": False, "error": str(e)}

    def cleanup_expired_cache(self, days: int = 7) -> int:
        """清理过期的token缓存

        Args:
            days: 过期天数

        Returns:
            清理的数量
        """
        try:
            with get_db() as db:
                cursor = db.execute("""
                    DELETE FROM account_token_cache
                    WHERE updated_at < datetime('now', '-{} days')
                """.format(days))
                db.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Failed to cleanup expired token cache: {str(e)}")
            return 0