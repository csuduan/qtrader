"""
认证相关API路由
包含登录、Token验证等功能
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select

from qtrader.manager.api.responses import error_response, success_response
from qtrader.models.po import UserPo
from qtrader.utils.database import get_database
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["认证"])
security = HTTPBearer()

# JWT 配置
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24小时

# PBKDF2 密码哈希参数
_PBKDF2_ITERATIONS = 100_000
_PBKDF2_PREFIX = "pbkdf2_sha256"

_secret_key_cache: str | None = None


def get_secret_key() -> str:
    """
    获取 JWT 签名密钥

    优先级：环境变量 QTRADER_JWT_SECRET > config.yaml 的 admin.jwt_secret。
    均未配置时生成临时随机密钥（重启后所有 token 失效）并告警。

    Returns:
        JWT 签名密钥
    """
    global _secret_key_cache
    if _secret_key_cache:
        return _secret_key_cache

    key = os.environ.get("QTRADER_JWT_SECRET", "").strip()
    if not key:
        from qtrader.utils.config_loader import get_config_loader

        key = (get_config_loader().load_config().admin.jwt_secret or "").strip()
    if not key:
        key = secrets.token_hex(32)
        logger.warning(
            "未配置 JWT 密钥（admin.jwt_secret 或环境变量 QTRADER_JWT_SECRET），"
            "已生成临时随机密钥，重启后所有登录态将失效"
        )
    _secret_key_cache = key
    return key


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
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    token = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)
    return token


def verify_token(token: str) -> dict | None:
    """
    验证JWT Token

    Args:
        token: JWT Token字符串

    Returns:
        解码后的payload，验证失败返回None
    """
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"无效的Token: {e}")
        return None


def hash_password(password: str) -> str:
    """
    对密码进行哈希处理（PBKDF2-HMAC-SHA256，随机盐）

    Args:
        password: 明文密码

    Returns:
        密码哈希，格式: pbkdf2_sha256$iterations$salt_hex$hash_hex
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_PREFIX}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """
    校验密码

    兼容历史遗留的无盐 SHA256 哈希，命中旧格式时需由调用方升级为 PBKDF2。

    Args:
        password: 明文密码
        stored: 数据库中存储的哈希

    Returns:
        (是否匹配, 是否需要升级哈希)
    """
    if stored.startswith(f"{_PBKDF2_PREFIX}$"):
        try:
            _, iterations, salt_hex, hash_hex = stored.split("$")
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
            )
            return secrets.compare_digest(digest.hex(), hash_hex), False
        except (ValueError, TypeError):
            return False, False
    # 旧格式：无盐 SHA256
    legacy = hashlib.sha256(password.encode()).hexdigest()
    return secrets.compare_digest(legacy, stored), True


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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


async def require_trader(current_user: dict = Depends(get_current_user)) -> dict:
    """
    要求交易权限（admin 或 trader 角色，guest 只读）

    Args:
        current_user: 当前用户信息

    Returns:
        用户信息

    Raises:
        HTTPException: 权限不足
    """
    if current_user["role"] not in ("admin", "trader"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要交易权限")
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
        matched, need_upgrade = (
            verify_password(request.password, user.password) if user else (False, False)
        )

        if not user or not matched:
            logger.warning(f"登录失败: 用户名或密码错误 - {request.username}")
            return JSONResponse(
                content={"code": 4001, "message": "用户名或密码错误", "data": None}, status_code=200
            )

        if not user.is_active:
            logger.warning(f"登录失败: 用户已被禁用 - {request.username}")
            return JSONResponse(
                content={"code": 4002, "message": "用户已被禁用", "data": None}, status_code=200
            )

        # 旧格式（无盐 SHA256）登录成功后升级为 PBKDF2
        if need_upgrade:
            user.password = hash_password(request.password)

        # 更新最后登录时间
        user.last_login = datetime.now()
        session.commit()

        # 生成Token
        token = create_access_token(user.user_id, user.role)

        logger.info(f"用户登录成功: {request.username}, 角色: {user.role}")

        return success_response(
            data={"token": token, "user": {"user_id": user.user_id, "role": user.role}},
            message="登录成功",
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
        data={"user_id": current_user["user_id"], "role": current_user["role"]},
        message="获取用户信息成功",
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
    """初始化管理员用户

    从 config.yaml 读取 admin 配置。仅在用户不存在时创建；
    已存在的用户不覆盖密码（密码修改以界面/数据库为准）。
    其他用户由 admin 手动创建。
    """
    from qtrader.utils.config_loader import get_config_loader

    db = get_database()
    config_loader = get_config_loader()
    app_config = config_loader.load_config()

    admin_config = app_config.admin
    admin_user_id = admin_config.user
    admin_password = admin_config.password

    with db.get_session() as session:
        # 查询管理员用户是否存在
        stmt = select(UserPo).where(UserPo.user_id == admin_user_id)
        result = session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            # 用户已存在，不覆盖密码，仅确保角色与启用状态
            changed = False
            if user.role != "admin":
                user.role = "admin"
                changed = True
            if not user.is_active:
                user.is_active = True
                changed = True
            if changed:
                user.updated_at = datetime.now()
                session.commit()
                logger.info(f"管理员用户状态已校正: {admin_user_id}")
            return

        if not admin_password:
            logger.error(
                "未配置管理员密码（config.yaml 的 admin.password），跳过管理员初始化。"
                "请配置后重启，或通过数据库手动创建管理员用户"
            )
            return

        # 用户不存在，创建新用户
        user = UserPo(
            user_id=admin_user_id,
            password=hash_password(admin_password),
            role="admin",
            is_active=True,
        )
        session.add(user)
        session.commit()
        logger.info(f"创建管理员用户: {admin_user_id}")
