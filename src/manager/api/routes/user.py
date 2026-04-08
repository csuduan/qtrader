"""
用户管理 API 路由
提供用户增删改查功能，仅管理员可访问
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.models.po import UserPo
from src.utils.database import get_database
from src.utils.logger import get_logger
from src.manager.api.responses import success_response, error_response
from src.manager.api.routes.auth import require_admin, hash_password

logger = get_logger(__name__)
router = APIRouter(prefix="/api/admin/users", tags=["用户管理"])


# ============ 请求/响应模型 ============

class UserCreateRequest(BaseModel):
    """创建用户请求"""
    username: str = Field(..., min_length=3, max_length=20, description="用户名")
    password: str = Field(..., min_length=6, max_length=20, description="密码")
    role: str = Field(..., description="角色: admin/trader/guest")


class UserUpdateRequest(BaseModel):
    """更新用户请求"""
    username: Optional[str] = Field(None, min_length=3, max_length=20, description="用户名")
    password: Optional[str] = Field(None, min_length=6, max_length=20, description="密码")
    role: Optional[str] = Field(None, description="角色: admin/trader/guest")


class UserResponse(BaseModel):
    """用户响应"""
    user_id: str
    username: str
    role: str
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


# ============ API 路由 ============

@router.get("")
async def get_users(current_user: dict = Depends(require_admin)):
    """
    获取用户列表

    Returns:
        统一响应格式: {code: 0, message: "success", data: [用户列表]}
    """
    db = get_database()

    with db.get_session() as session:
        stmt = select(UserPo).order_by(UserPo.created_at.desc())
        result = session.execute(stmt)
        users = result.scalars().all()

        user_list = []
        for user in users:
            user_list.append({
                "user_id": user.user_id,
                "username": user.user_id,  # 使用 user_id 作为 username
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            })

        logger.info(f"管理员 {current_user['user_id']} 获取用户列表，共 {len(user_list)} 个用户")
        return success_response(data=user_list)


@router.post("")
async def create_user(
    request: UserCreateRequest,
    current_user: dict = Depends(require_admin)
):
    """
    创建新用户

    Args:
        request: 创建用户请求

    Returns:
        统一响应格式: {code: 0, message: "success", data: 用户信息}
    """
    db = get_database()

    with db.get_session() as session:
        # 检查用户名是否已存在
        stmt = select(UserPo).where(UserPo.user_id == request.username)
        result = session.execute(stmt)
        if result.scalar_one_or_none():
            return error_response(message="用户名已存在", code=4001)

        # 验证角色
        if request.role not in ["admin", "trader", "guest"]:
            return error_response(message="无效的角色", code=4002)

        # 创建新用户
        new_user = UserPo(
            user_id=request.username,
            password=hash_password(request.password),
            role=request.role,
            is_active=True
        )
        session.add(new_user)
        session.commit()

        logger.info(f"管理员 {current_user['user_id']} 创建用户: {request.username}, 角色: {request.role}")

        return success_response(
            data={
                "user_id": new_user.user_id,
                "username": new_user.user_id,
                "role": new_user.role,
                "is_active": new_user.is_active,
                "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
                "updated_at": new_user.updated_at.isoformat() if new_user.updated_at else None
            },
            message="用户已创建"
        )


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: dict = Depends(require_admin)
):
    """
    更新用户信息

    Args:
        user_id: 用户ID
        request: 更新用户请求

    Returns:
        统一响应格式: {code: 0, message: "success", data: 用户信息}
    """
    db = get_database()

    with db.get_session() as session:
        # 查询用户
        stmt = select(UserPo).where(UserPo.user_id == user_id)
        result = session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return error_response(message="用户不存在", code=404)

        # 不能修改自己的角色（防止管理员把自己降级）
        if user_id == current_user["user_id"] and request.role and request.role != user.role:
            return error_response(message="不能修改自己的角色", code=403)

        # 更新字段
        if request.username and request.username != user_id:
            # 检查新用户名是否已存在
            stmt = select(UserPo).where(UserPo.user_id == request.username)
            result = session.execute(stmt)
            if result.scalar_one_or_none():
                return error_response(message="用户名已存在", code=4001)
            # 注意：这里不实际修改 user_id，因为那是主键
            # 如果需要支持修改用户名，需要额外处理

        if request.password:
            user.password = hash_password(request.password)

        if request.role:
            if request.role not in ["admin", "trader", "guest"]:
                return error_response(message="无效的角色", code=4002)
            user.role = request.role

        user.updated_at = datetime.now()
        session.commit()

        logger.info(f"管理员 {current_user['user_id']} 更新用户: {user_id}")

        return success_response(
            data={
                "user_id": user.user_id,
                "username": user.user_id,
                "role": user.role,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            },
            message="用户已更新"
        )


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    current_user: dict = Depends(require_admin)
):
    """
    删除用户

    Args:
        user_id: 用户ID

    Returns:
        统一响应格式: {code: 0, message: "success", data: null}
    """
    # 不能删除自己
    if user_id == current_user["user_id"]:
        return error_response(message="不能删除当前登录用户", code=403)

    db = get_database()

    with db.get_session() as session:
        # 查询用户
        stmt = select(UserPo).where(UserPo.user_id == user_id)
        result = session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return error_response(message="用户不存在", code=404)

        # 删除用户
        session.delete(user)
        session.commit()

        logger.info(f"管理员 {current_user['user_id']} 删除用户: {user_id}")

        return success_response(message="用户已删除")
