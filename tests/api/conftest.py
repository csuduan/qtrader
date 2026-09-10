"""
API 测试公共夹具（真实后端，最小化 mock）

前置条件（测试不负责拉起进程）：
- Manager 已启动：uv run python run_manager.py（默认 http://localhost:8000）
- DQ Trader 已连接（写路径用例需要，读路径部分用例也需要后端数据）

门控机制（沿用 E2E 真实模式惯例，未就绪时 skip 而非 fail）：
- 后端在线探测：session 级 GET /health（AuthMiddleware 白名单，无需 token）
- 登录凭据：E2E_USERNAME / E2E_PASSWORD 环境变量 → POST /api/auth/login 取 token
- 交易时段守卫：写路径用例先 require_trading_session()，非交易时段 skip
"""

import os

import httpx
import pytest

from qtrader.utils.trading_session import is_symbol_trading_time

API_BASE_URL = os.environ.get("API_TEST_BASE_URL", "http://localhost:8000")

E2E_USERNAME = os.environ.get("E2E_USERNAME", "")
E2E_PASSWORD = os.environ.get("E2E_PASSWORD", "")

# 测试唯一允许使用的交易账户（模拟盘）
E2E_ACCOUNT_ID = "DQ"

# 写路径用例使用的合约（主力合约会换月，可用环境变量覆盖）
E2E_SYMBOL = os.environ.get("E2E_SYMBOL", "SHFE.rb2701")


def require_trading_session(symbol: str = E2E_SYMBOL) -> None:
    """写路径用例的交易时段守卫：非交易时段 skip 而非 fail"""
    if not is_symbol_trading_time(symbol):
        pytest.skip(f"{symbol} 非交易时段，跳过真实交易用例")


@pytest.fixture(scope="session")
def api_client() -> httpx.Client:
    """已登录的 API 客户端：探测后端在线 → 登录取 token → 带 Bearer 头"""
    probe = httpx.get(f"{API_BASE_URL}/health", timeout=3.0)
    if probe.status_code != 200 or probe.json().get("status") != "ok":
        pytest.skip(f"后端未就绪（{API_BASE_URL} /health 异常），跳过 API 测试")

    if not (E2E_USERNAME and E2E_PASSWORD):
        pytest.skip("未设置 E2E_USERNAME / E2E_PASSWORD，跳过需要登录的 API 测试")

    resp = httpx.post(
        f"{API_BASE_URL}/api/auth/login",
        json={"username": E2E_USERNAME, "password": E2E_PASSWORD},
        timeout=5.0,
    )
    body = resp.json()
    if resp.status_code != 200 or body.get("code") != 0:
        pytest.skip(f"登录失败：{body.get('message')}，跳过 API 测试")

    token = body["data"]["token"]
    with httpx.Client(
        base_url=API_BASE_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    ) as client:
        yield client


@pytest.fixture()
def require_dq_connected(api_client):
    """写路径用例的前置检查：DQ Trader 未连接则 skip"""
    resp = api_client.get("/api/system/status", params={"account_id": E2E_ACCOUNT_ID})
    connected = bool(resp.json().get("data", {}).get("connected"))
    if not connected:
        pytest.skip(f"Trader [{E2E_ACCOUNT_ID}] 未连接，跳过交易用例")
    return api_client
