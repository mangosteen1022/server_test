"""健康检查路由"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    """健康检查"""
    return {"ok": True}


@router.get("/")
def root():
    """根路径"""
    return {"ok": True, "ui": "/index"}
