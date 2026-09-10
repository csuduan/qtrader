"""
鉴权中间件与 JWT 工具单元测试

覆盖公开路径白名单、Bearer Token 校验、guest 只读权限控制，
以及 JWT 创建/验证与密码哈希的往返行为。
"""

from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from starlette.requests import Request
from starlette.responses import Response

from qtrader.manager.api.middleware.auth import AuthMiddleware
from qtrader.manager.api.routes.auth import (
    create_access_token,
    get_secret_key,
    hash_password,
    verify_password,
    verify_token,
)


def make_middleware() -> AuthMiddleware:
    return AuthMiddleware(MagicMock())


def make_request(path: str = "/api/account", method: str = "GET", headers: dict | None = None):
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "headers": raw_headers,
        "query_string": b"",
    }
    return Request(scope)


def make_call_next() -> AsyncMock:
    return AsyncMock(return_value=Response("ok"))


@pytest.mark.unit
class TestPublicPaths:
    """公开路径白名单"""

    def test_exact_match(self):
        mw = make_middleware()
        for path in ("/", "/health", "/api/auth/login"):
            assert mw._is_public_path(path) is True

    def test_prefix_match(self):
        mw = make_middleware()
        assert mw._is_public_path("/docs/swagger") is True
        assert mw._is_public_path("/static/app.js") is True

    def test_non_public(self):
        mw = make_middleware()
        assert mw._is_public_path("/api/account") is False
        assert mw._is_public_path("/api/auth/me") is False


@pytest.mark.unit
class TestDispatchPassThrough:
    """免鉴权路径直接放行"""

    @pytest.mark.asyncio
    async def test_public_path(self):
        mw = make_middleware()
        call_next = make_call_next()
        resp = await mw.dispatch(make_request("/health"), call_next)
        call_next.assert_awaited_once()
        assert resp.body == b"ok"

    @pytest.mark.asyncio
    async def test_non_api_path(self):
        mw = make_middleware()
        call_next = make_call_next()
        await mw.dispatch(make_request("/favicon.ico"), call_next)
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_websocket_path(self):
        mw = make_middleware()
        call_next = make_call_next()
        await mw.dispatch(make_request("/ws"), call_next)
        call_next.assert_awaited_once()


@pytest.mark.unit
class TestDispatchAuth:
    """Token 校验"""

    @pytest.mark.asyncio
    async def test_missing_header_401(self):
        mw = make_middleware()
        call_next = make_call_next()
        resp = await mw.dispatch(make_request("/api/account"), call_next)
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bad_scheme_401(self):
        mw = make_middleware()
        call_next = make_call_next()
        resp = await mw.dispatch(
            make_request("/api/account", headers={"Authorization": "Basic abc"}), call_next
        )
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_token_401(self):
        mw = make_middleware()
        call_next = make_call_next()
        resp = await mw.dispatch(
            make_request("/api/account", headers={"Authorization": "Bearer bad.token"}),
            call_next,
        )
        assert resp.status_code == 401
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_token_passes_and_sets_state(self):
        mw = make_middleware()
        call_next = make_call_next()
        token = create_access_token("user_1", "admin")
        request = make_request("/api/account", headers={"Authorization": f"Bearer {token}"})

        resp = await mw.dispatch(request, call_next)

        assert resp.body == b"ok"
        assert request.state.user == {"user_id": "user_1", "role": "admin"}

    @pytest.mark.asyncio
    async def test_expired_token_401(self):
        mw = make_middleware()
        call_next = make_call_next()
        expired = pyjwt.encode(
            {"sub": "u", "role": "admin", "exp": 0}, get_secret_key(), algorithm="HS256"
        )
        resp = await mw.dispatch(
            make_request("/api/account", headers={"Authorization": f"Bearer {expired}"}),
            call_next,
        )
        assert resp.status_code == 401


@pytest.mark.unit
class TestGuestWriteControl:
    """guest 角色只读控制"""

    @pytest.mark.asyncio
    async def test_guest_write_403(self):
        mw = make_middleware()
        call_next = make_call_next()
        token = create_access_token("guest_1", "guest")
        resp = await mw.dispatch(
            make_request(
                "/api/orders", method="POST", headers={"Authorization": f"Bearer {token}"}
            ),
            call_next,
        )
        assert resp.status_code == 403
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_guest_get_allowed(self):
        mw = make_middleware()
        call_next = make_call_next()
        token = create_access_token("guest_1", "guest")
        await mw.dispatch(
            make_request("/api/account", headers={"Authorization": f"Bearer {token}"}), call_next
        )
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_guest_logout_allowed(self):
        mw = make_middleware()
        call_next = make_call_next()
        token = create_access_token("guest_1", "guest")
        await mw.dispatch(
            make_request(
                "/api/auth/logout", method="POST", headers={"Authorization": f"Bearer {token}"}
            ),
            call_next,
        )
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trader_write_allowed(self):
        mw = make_middleware()
        call_next = make_call_next()
        token = create_access_token("t1", "trader")
        await mw.dispatch(
            make_request(
                "/api/orders", method="POST", headers={"Authorization": f"Bearer {token}"}
            ),
            call_next,
        )
        call_next.assert_awaited_once()


@pytest.mark.unit
class TestJwtUtils:
    """JWT 与密码工具函数"""

    def test_create_and_verify_roundtrip(self):
        token = create_access_token("user_1", "admin")
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "user_1"
        assert payload["role"] == "admin"

    def test_verify_garbage_returns_none(self):
        assert verify_token("not-a-jwt") is None

    def test_verify_wrong_secret_returns_none(self):
        token = pyjwt.encode({"sub": "u"}, "other-secret", algorithm="HS256")
        assert verify_token(token) is None

    def test_password_hash_roundtrip(self):
        stored = hash_password("s3cret")
        ok, needs_rehash = verify_password("s3cret", stored)
        assert ok is True
        assert needs_rehash is False

    def test_password_wrong(self):
        stored = hash_password("s3cret")
        ok, _ = verify_password("wrong", stored)
        assert ok is False

    def test_password_hash_is_salted(self):
        assert hash_password("same") != hash_password("same")
