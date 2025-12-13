"""
routes/auth.py
用户认证路由 & 权限依赖
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from services.auth_service import AuthService

router = APIRouter(tags=["System Auth"])

# 定义 Token 获取地址，FastAPI Swagger UI 会用到
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str


# ==================== 依赖项 (Dependencies) ====================

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    依赖：验证 Token 并获取当前用户
    用于保护需要登录的接口
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )

    service = AuthService()
    payload = service.decode_token(token)
    if payload is None:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = service.get_user_by_id(int(user_id))
    if user is None:
        raise credentials_exception

    return user


async def get_current_admin(current_user: dict = Depends(get_current_user)):
    """
    依赖：仅限管理员访问
    用于保护资源分配、项目创建等接口
    """
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足：需要管理员权限"
        )
    return current_user


# ==================== 接口实现 ====================

@router.post("/auth/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """系统用户登录接口"""
    service = AuthService()

    # 验证用户
    user = service.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 签发 Token，包含 user_id 和 role
    access_token = service.create_access_token(
        data={"sub": str(user["id"]), "role": user["role"],"username": user['name']}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user["role"],
        "username": user["name"]
    }