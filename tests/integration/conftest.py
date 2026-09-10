"""
集成测试公共夹具

三个关键点：
- 置空 lifespan：跳过生产启动（连 PostgreSQL、拉起 Trader 进程、初始化默认用户）
- 用 MagicMock 替换 AppContext.get_trading_manager：同时覆盖
  Depends(get_trading_manager) 与路由函数体内的 ctx.get_trading_manager() 二次取用
- 统一带 admin JWT 请求头，绕过 AuthMiddleware 的 401 拦截
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qtrader.app_context import AppContext
from qtrader.manager.api.routes.auth import create_access_token


@asynccontextmanager
async def _null_lifespan(app: FastAPI):
    """空生命周期，不做任何生产初始化"""
    yield


@pytest.fixture
def mock_trading_manager() -> MagicMock:
    """覆盖路由会用到的 TradingManager 接口"""
    mock = MagicMock()
    mock.traders = {}
    mock.account_configs = []
    mock.get_all_account_ids = MagicMock(return_value=[])
    mock.get_trader = MagicMock(return_value=None)
    mock.get_account = AsyncMock(return_value=None)
    mock.get_all_accounts = AsyncMock(return_value=[])
    mock.get_positions = AsyncMock(return_value={})
    mock.get_orders = AsyncMock(return_value=[])
    mock.get_active_orders = AsyncMock(return_value=[])
    mock.get_trades = AsyncMock(return_value=[])
    mock.start_trader = AsyncMock(return_value=True)
    mock.stop_trader = AsyncMock(return_value=True)
    return mock


def _build_client(mock_trading_manager: MagicMock, token: str | None) -> TestClient:
    from qtrader.manager.app import create_app

    app = create_app()
    app.router.lifespan_context = _null_lifespan

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with patch.object(
        AppContext, "get_trading_manager", return_value=mock_trading_manager
    ), TestClient(app, headers=headers) as client:
        yield client


@pytest.fixture
def client(mock_trading_manager) -> TestClient:
    """带 admin token 的已鉴权客户端"""
    admin_token = create_access_token("itest_admin", "admin")
    yield from _build_client(mock_trading_manager, admin_token)


@pytest.fixture
def anon_client(mock_trading_manager) -> TestClient:
    """不带 token 的客户端（用于鉴权拦截断言）"""
    yield from _build_client(mock_trading_manager, None)
