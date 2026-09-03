"""
鉴权中间件
统一拦截所有请求并验证JWT Token
"""

from fastapi import Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from qtrader.manager.api.routes.auth import verify_token
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT鉴权中间件

    统一拦截所有HTTP请求，验证Authorization头中的JWT Token。
    公开接口（白名单）无需鉴权。
    """

    # 公开接口白名单（支持完整路径或前缀匹配）
    PUBLIC_PATHS: list[str] = [
        "/",  # 根路径
        "/docs",  # API文档
        "/openapi.json",  # OpenAPI规范
        "/api/auth/login",  # 登录接口
        "/api/auth/register",  # 注册接口（如有）
        "/health",  # 健康检查
    ]

    # 公开路径前缀（以这些前缀开头的路径都免鉴权）
    PUBLIC_PREFIXES: list[str] = [
        "/docs/",
        "/redoc",
        "/static/",
    ]

    # guest（只读角色）允许执行的写操作
    GUEST_WRITE_ALLOWED: list[str] = [
        "/api/auth/logout",  # 登出自身
    ]

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    def _is_public_path(self, path: str) -> bool:
        """
        检查路径是否为公开接口

        Args:
            path: 请求路径

        Returns:
            是否为公开接口
        """
        # 完全匹配
        if path in self.PUBLIC_PATHS:
            return True

        # 前缀匹配
        for prefix in self.PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return True

        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        处理每个请求

        Args:
            request: FastAPI请求对象
            call_next: 下一个中间件或路由处理函数

        Returns:
            Response对象
        """
        path = request.url.path

        # 1. 公开接口直接放行
        if self._is_public_path(path):
            return await call_next(request)

        # 2. 只处理API请求（以/api开头的路径）
        if not path.startswith("/api"):
            return await call_next(request)

        # 3. WebSocket请求不在这里处理（由WebSocket自己处理）
        if path == "/ws":
            return await call_next(request)

        # 4. 获取并验证Token
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            logger.warning(f"鉴权失败: 缺少Authorization头 - {path}")
            return Response(
                content='{"code": 401, "message": "缺少认证凭证", "data": null}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                media_type="application/json",
            )

        # 解析Bearer Token
        try:
            scheme, _, token = auth_header.partition(" ")
            if scheme.lower() != "bearer" or not token:
                logger.warning(f"鉴权失败: 无效的Authorization格式 - {path}")
                return Response(
                    content='{"code": 401, "message": "无效的认证格式，请使用Bearer Token", "data": null}',
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                    media_type="application/json",
                )

            # 验证Token
            payload = verify_token(token)

            if payload is None:
                logger.warning(f"鉴权失败: 无效的Token - {path}")
                return Response(
                    content='{"code": 401, "message": "认证凭证无效或已过期", "data": null}',
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                    media_type="application/json",
                )

            # Token有效，将用户信息存入请求状态
            request.state.user = {"user_id": payload.get("sub"), "role": payload.get("role")}

            # 写操作权限控制：guest 角色只读（下单/撤单/平仓/启停 Trader 等需 admin 或 trader）
            if (
                request.method.upper() not in ("GET", "HEAD", "OPTIONS")
                and payload.get("role") not in ("admin", "trader")
                and path not in self.GUEST_WRITE_ALLOWED
            ):
                logger.warning(
                    f"权限不足: {payload.get('sub')}({payload.get('role')}) "
                    f"尝试写操作 {request.method} {path}"
                )
                return Response(
                    content='{"code": 403, "message": "权限不足：只读账户无法执行此操作", "data": null}',
                    status_code=403,
                    media_type="application/json",
                )

            logger.debug(f"鉴权成功: {payload.get('sub')} - {path}")

        except Exception as e:
            logger.error(f"鉴权处理异常: {e} - {path}")
            return Response(
                content='{"code": 401, "message": "认证处理失败", "data": null}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                media_type="application/json",
            )

        # 继续处理请求
        return await call_next(request)
