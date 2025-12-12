"""FastAPI 应用工厂"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from settings import (
    API_TITLE,
    API_VERSION,
    CORS_ORIGINS,
    CORS_ALLOW_CREDENTIALS,
    CORS_ALLOW_METHODS,
    CORS_ALLOW_HEADERS,
    STATIC_DIR,
)
from routes import include_all_routers


def create_app() -> FastAPI:
    """创建FastAPI应用"""

    # 创建应用实例
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # 添加CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=CORS_ALLOW_CREDENTIALS,
        allow_methods=CORS_ALLOW_METHODS,
        allow_headers=CORS_ALLOW_HEADERS,
    )

    # 注册所有路由
    include_all_routers(app)

    # 挂载静态文件
    if STATIC_DIR.exists():
        app.mount("/index", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

    return app


# 为了兼容原有代码，也可以直接导出app实例
app = create_app()

if __name__ == '__main__':
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
