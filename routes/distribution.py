"""
routes/distribution.py
分配管理 API - 仅限管理员访问
"""
from fastapi import APIRouter, Depends, Body, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel

from services.distribution_service import DistributionService
# 注意：这里引入的是新创建的 auth 模块中的依赖
from routes.auth import get_current_admin

router = APIRouter(prefix="/distribution", tags=["Distribution"])

# === 请求模型 ===
class ProjectCreate(BaseModel):
    name: str

class UserCreate(BaseModel):
    name: str
    password: str
    role: str = "user"  # 默认为普通用户

class AssignmentReq(BaseModel):
    project_id: int
    user_id: int
    count: int

# === 接口实现 ===

@router.get("/projects")
def list_projects(admin: dict = Depends(get_current_admin)):
    """获取项目列表"""
    return DistributionService().list_projects()

@router.post("/projects")
def create_project(item: ProjectCreate, admin: dict = Depends(get_current_admin)):
    """创建新项目"""
    return {"id": DistributionService().create_project(item.name)}

@router.get("/users")
def list_users(admin: dict = Depends(get_current_admin)):
    """获取用户列表"""
    return DistributionService().list_users()

@router.post("/users")
def create_user(item: UserCreate, admin: dict = Depends(get_current_admin)):
    """创建新用户"""
    return {"id": DistributionService().create_user(item.name, item.password, item.role)}

@router.post("/assign")
def assign_accounts(item: AssignmentReq, admin: dict = Depends(get_current_admin)):
    """执行账号分配"""
    count = DistributionService().assign_accounts(item.project_id, item.user_id, item.count)
    return {"success": True, "message": f"成功分配 {count} 个账号"}

@router.get("/projects/{project_id}/stats")
def get_project_stats(project_id: int, admin: dict = Depends(get_current_admin)):
    """获取项目分配统计"""
    return DistributionService().get_project_stats(project_id)