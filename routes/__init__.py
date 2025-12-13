"""API 路由模块"""

from .health import router as health_router
from .accounts import router as accounts_router
from .mails import router as mails_router
from .folders import router as folders_router
from .tokens import router as tokens_router
from .oauth import router as oauth_router
from .auth import router as auth_router


def include_all_routers(app):
    """注册所有路由到 FastAPI 应用"""
    app.include_router(health_router, tags=["Health"])
    app.include_router(accounts_router, prefix="/accounts", tags=["Accounts"])
    app.include_router(mails_router, prefix="/mail", tags=["Mails"])
    app.include_router(folders_router, tags=["Folders"])
    app.include_router(tokens_router, tags=["Tokens"])
    app.include_router(oauth_router, tags=["OAuth"])  # 基于group_id的认证和同步
    app.include_router(auth_router, tags=["Auth"])  # 基于group_id的认证和同步


__all__ = ["include_all_routers"]
