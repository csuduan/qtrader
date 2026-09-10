"""
API 集成冒烟测试

走完整 FastAPI 栈（中间件 + 路由 + 依赖注入），TradingManager 全程 mock。
断言使用确定性数据（mock 返回真实模型对象），不依赖运行环境。
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qtrader.models.object import (
    AccountData,
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderStatus,
    PositionData,
    TradeData,
)


def make_account() -> AccountData:
    return AccountData(
        account_id="DQ",
        user_id="user001",
        broker_name="测试期货",
        broker_type="CTP",
        balance=100000.0,
        available=50000.0,
    )


def make_position() -> PositionData:
    return PositionData(
        symbol="SHFE.rb2505",
        exchange=Exchange.SHFE,
        multiple=10,
        pos_long_td=2,
        hold_price_long=3450.0,
        last_price=3500.0,
    )


def make_order() -> OrderData:
    return OrderData(
        order_id="ord_1",
        symbol="SHFE.rb2505",
        account_id="DQ",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=2,
        price=Decimal("3450"),
        status=OrderStatus.PENDING,
    )


def make_trade() -> TradeData:
    return TradeData(
        trade_id="t_1",
        order_id="ord_1",
        symbol="SHFE.rb2505",
        exchange=Exchange.SHFE,
        direction=Direction.BUY,
        offset=Offset.OPEN,
        price=Decimal("3450"),
        volume=2,
        account_id="DQ",
        trade_time=int(datetime(2026, 9, 1, 10, 0).timestamp()),
    )


@pytest.mark.integration
class TestSystemAPI:
    """系统级公开端点"""

    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.integration
class TestAuthEnforcement:
    """鉴权中间件在完整应用栈上的行为"""

    def test_no_token_401(self, anon_client):
        resp = anon_client.get("/api/account", params={"account_id": "DQ"})
        assert resp.status_code == 401

    def test_bad_token_401(self, anon_client):
        resp = anon_client.get(
            "/api/account",
            params={"account_id": "DQ"},
            headers={"Authorization": "Bearer bad.token"},
        )
        assert resp.status_code == 401


@pytest.mark.integration
class TestAccountAPI:
    """账户端点（前缀 /api/account）"""

    def test_get_account_info(self, client, mock_trading_manager):
        mock_trading_manager.get_account = AsyncMock(return_value=make_account())

        resp = client.get("/api/account", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["account_id"] == "DQ"
        assert body["data"]["balance"] == 100000.0
        mock_trading_manager.get_account.assert_awaited_once_with("DQ")

    def test_get_account_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_account = AsyncMock(return_value=None)

        resp = client.get("/api/account", params={"account_id": "NOPE"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_get_all_accounts(self, client, mock_trading_manager):
        mock_trading_manager.get_all_accounts_cached = MagicMock(return_value=[make_account()])

        resp = client.get("/api/account/all")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 1
        assert body["data"][0]["account_id"] == "DQ"


@pytest.mark.integration
class TestPositionAPI:
    """持仓端点（前缀 /api/position）"""

    def test_get_positions(self, client, mock_trading_manager):
        # get_positions 返回 {account_id: [PositionData]}，且按启用的账户过滤
        mock_trading_manager.account_configs = [SimpleNamespace(account_id="DQ", enabled=True)]
        mock_trading_manager.get_positions = AsyncMock(return_value={"DQ": [make_position()]})

        resp = client.get("/api/position", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 1
        assert body["data"][0]["symbol"] == "SHFE.rb2505"
        assert body["data"][0]["account_id"] == "DQ"


@pytest.mark.integration
class TestOrderAPI:
    """委托单端点（前缀 /api/order）"""

    def test_get_alive_orders(self, client, mock_trading_manager):
        mock_trading_manager.get_active_orders = AsyncMock(return_value=[make_order()])

        resp = client.get("/api/order", params={"status": "ALIVE", "account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"][0]["order_id"] == "ord_1"
        assert body["data"][0]["direction"] == "BUY"

    def test_get_finished_orders_without_db(self, client):
        """无数据库时 FINISHED 查询返回明确错误而非崩溃"""
        resp = client.get("/api/order", params={"status": "FINISHED", "account_id": "DQ"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "数据库未初始化" in resp.json()["message"]

    def test_create_manual_order(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.send_order_request = AsyncMock(return_value="ord_new")
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            "/api/order",
            json={
                "account_id": "DQ",
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
                "price": 3450,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["order_id"] == "ord_new"
        trader.send_order_request.assert_awaited_once()

    def test_create_order_trader_error_propagates(self, client, mock_trading_manager):
        """下单异常时错误消息应透传给前端（含 Trader 回传的真实失败原因）"""
        trader = MagicMock()
        # SocketClient 收到 IPC error 响应时抛出 Exception(真实原因)
        trader.send_order_request = AsyncMock(
            side_effect=Exception("Exception: 盘中非交易时段，禁止报单: SHFE.rb2505")
        )
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            "/api/order",
            json={
                "account_id": "DQ",
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
                "price": 3450,
            },
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert "非交易时段" in body["message"]
        assert "SHFE.rb2505" in body["message"]

    def test_create_order_invalid_direction(self, client):
        resp = client.post(
            "/api/order",
            json={
                "account_id": "DQ",
                "symbol": "SHFE.rb2505",
                "direction": "WRONG",
                "offset": "OPEN",
                "volume": 1,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 400

    def test_create_order_unknown_account(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            "/api/order",
            json={
                "account_id": "GHOST",
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestTradeAPI:
    """成交端点（前缀 /api/trade）"""

    def test_get_today_trades(self, client, mock_trading_manager):
        mock_trading_manager.get_trades = AsyncMock(return_value=[make_trade()])

        resp = client.get("/api/trade", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"][0]["trade_id"] == "t_1"
        assert body["data"][0]["direction"] == "BUY"

    def test_get_history_trades_without_db(self, client):
        """无数据库时历史查询返回空列表而非崩溃"""
        resp = client.get("/api/trade", params={"account_id": "DQ", "date": "2026-01-01"})

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"] == []
