"""
services/auth_service.py
系统用户认证服务 - 处理登录验证和JWT
"""
import settings
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt

from database.factory import get_db
from utils.logger import get_logger

logger = get_logger(__name__)


class AuthService:
    """处理系统用户认证逻辑"""

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """验证用户名和密码"""
        with get_db() as db:
            user = db.execute(
                "SELECT id, name, password, role FROM users WHERE name = ?",
                (username,)
            ).fetchone()

            # 这里演示用明文，生产环境请使用 bcrypt.verify(password, user['password'])
            if not user or user["password"] != password:
                return None

            return dict(user)

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """生成 JWT Token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """解析 Token"""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            return payload
        except JWTError:
            return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """根据ID获取用户信息"""
        with get_db() as db:
            user = db.execute(
                "SELECT id, name, role FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
            if user:
                return dict(user)
            return None