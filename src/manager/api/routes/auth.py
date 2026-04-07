"""
认证相关API路由
包含登录、Token验证等功能
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select

from fastapi.responses import JSONResponse

from src.models.po import UserPo
from src.utils.database import get_database
from src.utils.logger import get_logger
from src.manager.api.responses import success_response, error_response

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["认证"])
security = HTTPBearer()

# JWT 配置
SECRET_KEY = "qtrader-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24小时


# ============ 请求模型 ============

class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


# ============ JWT Token 工具函数 ============

def create_access_token(user_id: str, role: str) -> str:
    """
    创建访问令牌
    
    Args:
        user_id: 用户ID
        role: 用户角色
        
    Returns:
        JWT Token字符串
    """
    try:
        import jwt
    except ImportError:
        # 如果没有 PyJWT，使用简单的 token 格式
        import base64
        import json
        payload = {
            "sub": user_id,
            "role": role,
            "exp": (datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()
        }
        token = base64.b64encode(json.dumps(payload).encode()).decode()
        return f"qtrader.{token}"
    
    import jwt
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def verify_token(token: str) -> Optional[dict]:
    """
    验证JWT Token
    
    Args:
        token: JWT Token字符串
        
    Returns:
        解码后的payload，验证失败返回None
    """
    try:
        import jwt
    except ImportError:
        # 简单 token 验证
        import base64
        import json
        if not token.startswith("qtrader."):
            return None
        try:
            encoded = token.split(".")[1]
            payload = json.loads(base64.b64decode(encoded).decode())
            exp = payload.get("exp", 0)
            if datetime.utcnow().timestamp() > exp:
                return None
            return payload
        except Exception:
            return None
    
    import jwt
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"无效的Token: {e}")
        return None


def hash_password(password: str) -> str:
    """
    对密码进行哈希处理
    
    Args:
        password: 明文密码
        
    Returns:
        密码哈希
    """
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


# ============ 依赖项 ============

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    获取当前登录用户
    
    Args:
        credentials: HTTP认证凭证
        
    Returns:
        用户信息字典
        
    Raises:
        HTTPException: 认证失败
    """
    token = credentials.credentials
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    role = payload.get("role")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法验证用户身份",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {"user_id": user_id, "role": role}


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    要求管理员权限
    
    Args:
        current_user: 当前用户信息
        
    Returns:
        用户信息
        
    Raises:
        HTTPException: 权限不足
    """
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    return current_user


# ============ API 路由 ============

@router.post("/login")
async def login(request: LoginRequest):
    """
    用户登录
    
    Args:
        request: 登录请求，包含用户名和密码
        
    Returns:
        统一响应格式: {code: 0, message: "success", data: {token, user}}
    """
    db = get_database()
    
    with db.get_session() as session:
        # 查询用户
        stmt = select(UserPo).where(UserPo.user_id == request.username)
        result = session.execute(stmt)
        user = result.scalar_one_or_none()
        
        # 验证用户存在且密码正确
        password_hash = hash_password(request.password)
        
        if not user or user.password != password_hash:
            logger.warning(f"登录失败: 用户名或密码错误 - {request.username}")
            return JSONResponse(
                content={"code": 4001, "message": "用户名或密码错误", "data": None},
                status_code=200
            )
        
        if not user.is_active:
            logger.warning(f"登录失败: 用户已被禁用 - {request.username}")
            return JSONResponse(
                content={"code": 4002, "message": "用户已被禁用", "data": None},
                status_code=200
            )
        
        # 更新最后登录时间
        user.last_login = datetime.now()
        session.commit()
        
        # 生成Token
        token = create_access_token(user.user_id, user.role)
        
        logger.info(f"用户登录成功: {request.username}, 角色: {user.role}")
        
        return success_response(
            data={
                "token": token,
                "user": {
                    "user_id": user.user_id,
                    "role": user.role
                }
            },
            message="登录成功"
        )


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    获取当前登录用户信息
    
    Args:
        current_user: 当前用户信息（由依赖注入）
        
    Returns:
        统一响应格式: {code: 0, message: "success", data: {user_id, role}}
    """
    return success_response(
        data={
            "user_id": current_user["user_id"],
            "role": current_user["role"]
        },
        message="获取用户信息成功"
    )


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """
    用户退出登录
    
    注：由于使用JWT，服务器端无法真正"注销"token，
    需要前端删除token即可。这里仅作记录。
    
    Args:
        current_user: 当前用户信息
        
    Returns:
        统一响应格式: {code: 0, message: "success", data: null}
    """
    logger.info(f"用户退出登录: {current_user['user_id']}")
    return success_response(message="退出登录成功")


# ============ 初始化默认用户 ============

def init_default_users():
    """初始化默认用户数据"""
    db = get_database()
    
    with db.get_session() as session:
        # 检查是否已有用户
        stmt = select(UserPo).limit(1)
        result = session.execute(stmt)
        if result.scalar_one_or_none():
            logger.info("用户表已有数据，跳过初始化")
            return
        
        # 创建默认用户
        default_users = [
            {
                "user_id": "duanqing",
                "password": "duanqing123",
                "role": "admin"
            },
            {
                "user_id": "caizijia",
                "password": "caizijia123",
                "role": "trader"
            }
        ]
        
        for user_data in default_users:
            user = UserPo(
                user_id=user_data["user_id"],
                password=hash_password(user_data["password"]),
                role=user_data["role"],
                is_active=True
            )
            session.add(user)
            logger.info(f"创建默认用户: {user_data['user_id']}, 角色: {user_data['role']}")
        
        session.commit()
        logger.info("默认用户初始化完成")
