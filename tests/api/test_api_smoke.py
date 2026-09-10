"""
API 冒烟测试（真实后端读路径）

覆盖核心读端点的可用性与响应结构（HTTP 200 + code==0 + 关键字段）。
不依赖交易时段，后端在线 + 登录凭据即可运行。
"""

import pytest

from tests.api.conftest import E2E_ACCOUNT_ID

pytestmark = pytest.mark.api


def test_health(api_client):
    """健康检查（白名单端点，无需 token 亦可通过客户端访问）"""
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_auth_me(api_client):
    """当前登录用户信息"""
    resp = api_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["user_id"]


def test_system_status(api_client):
    """系统状态（DQ 账户）"""
    resp = api_client.get("/api/system/status", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert "running" in body["data"]
    assert "connected" in body["data"]


def test_get_accounts(api_client):
    """账户列表（单账户返回对象，含 account_id）"""
    resp = api_client.get("/api/account")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], dict)
    assert body["data"]["account_id"] == E2E_ACCOUNT_ID


def test_get_positions(api_client):
    """持仓列表"""
    resp = api_client.get("/api/position", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list)


def test_get_orders(api_client):
    """委托单列表（status 必填：ALIVE/FINISHED/REJECTED）"""
    resp = api_client.get(
        "/api/order",
        params={"account_id": E2E_ACCOUNT_ID, "status": "ALIVE"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list)


def test_get_trades(api_client):
    """成交记录列表"""
    resp = api_client.get("/api/trade", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list)


def test_get_order_cmds(api_client):
    """报单指令列表（未完成 / 已完成）"""
    for status in ("active", "finished"):
        resp = api_client.get(
            "/api/order-cmd", params={"account_id": E2E_ACCOUNT_ID, "status": status}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert isinstance(body["data"], list)


def test_get_rotation_instructions(api_client):
    """换仓指令列表"""
    resp = api_client.get("/api/rotation", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0


def test_get_scheduled_tasks(api_client):
    """定时任务列表"""
    resp = api_client.get("/api/jobs", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], dict)
    assert "tasks" in body["data"]
    assert "count" in body["data"]


def test_get_alarm_stats(api_client):
    """告警统计"""
    resp = api_client.get("/api/alarm/stats", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0


def test_get_subscribed_quotes(api_client):
    """已订阅行情列表"""
    resp = api_client.get("/api/quote", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list)


def test_unauthorized_rejected():
    """无 token 访问受保护端点应 401（真实中间件链验证）"""
    import httpx

    from tests.api.conftest import API_BASE_URL

    resp = httpx.get(f"{API_BASE_URL}/api/account", timeout=5.0)
    assert resp.status_code == 401
