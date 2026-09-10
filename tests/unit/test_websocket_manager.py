"""
WebSocketManager 单元测试

覆盖连接管理、全量广播、行情订阅过滤与断连清理。
使用 AsyncMock WebSocket，不起真实服务器。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from qtrader.manager.api.websocket_manager import WebSocketManager


def make_ws() -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


@pytest.mark.unit
class TestConnectDisconnect:
    """连接与断开"""

    @pytest.mark.asyncio
    async def test_connect_registers(self):
        mgr = WebSocketManager()
        ws = make_ws()

        await mgr.connect(ws)

        ws.accept.assert_awaited_once()
        assert ws in mgr.active_connections
        assert mgr.quote_subscriptions[ws] is False

    @pytest.mark.asyncio
    async def test_disconnect_removes(self):
        mgr = WebSocketManager()
        ws = make_ws()
        await mgr.connect(ws)

        await mgr.disconnect(ws)

        assert ws not in mgr.active_connections
        assert ws not in mgr.quote_subscriptions

    @pytest.mark.asyncio
    async def test_disconnect_unknown_noop(self):
        mgr = WebSocketManager()
        await mgr.disconnect(make_ws())  # 未注册连接，不应抛错

    def test_set_quote_subscription(self):
        mgr = WebSocketManager()
        ws = make_ws()
        mgr.quote_subscriptions[ws] = False

        mgr.set_quote_subscription(ws, True)
        assert mgr.quote_subscriptions[ws] is True

    def test_set_quote_subscription_unknown_ignored(self):
        mgr = WebSocketManager()
        ws = make_ws()
        mgr.set_quote_subscription(ws, True)  # 未注册连接，不写入
        assert ws not in mgr.quote_subscriptions


@pytest.mark.unit
class TestBroadcast:
    """全量广播"""

    @pytest.mark.asyncio
    async def test_no_connections_noop(self):
        mgr = WebSocketManager()
        await mgr.broadcast({"type": "x"})  # 无连接，不应抛错

    @pytest.mark.asyncio
    async def test_broadcast_reaches_all(self):
        mgr = WebSocketManager()
        ws1, ws2 = make_ws(), make_ws()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        await mgr.broadcast({"type": "account_update", "data": {"balance": 1}})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()
        sent = ws1.send_text.await_args.args[0]
        assert '"account_update"' in sent
        assert '"balance"' in sent

    @pytest.mark.asyncio
    async def test_failed_send_cleans_up(self):
        mgr = WebSocketManager()
        good, bad = make_ws(), make_ws()
        bad.send_text = AsyncMock(side_effect=RuntimeError("closed"))
        await mgr.connect(good)
        await mgr.connect(bad)

        await mgr.broadcast({"type": "account_update", "data": {}})

        assert bad not in mgr.active_connections
        assert good in mgr.active_connections

    @pytest.mark.asyncio
    async def test_nan_payload_serialized(self):
        """NaN 序列化为 null，不应导致广播中断"""
        mgr = WebSocketManager()
        ws = make_ws()
        await mgr.connect(ws)

        await mgr.broadcast({"type": "account_update", "data": {"x": float("nan")}})

        ws.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_datetime_payload_serialized(self):
        """datetime 由 orjson 原生序列化"""
        from datetime import datetime

        mgr = WebSocketManager()
        ws = make_ws()
        await mgr.connect(ws)

        await mgr.broadcast({"type": "trade_update", "data": {"t": datetime(2026, 9, 4, 10, 0)}})

        ws.send_text.assert_awaited_once()
        assert "2026-09-04" in ws.send_text.await_args.args[0]


@pytest.mark.unit
class TestSubscriberBroadcast:
    """行情订阅过滤广播"""

    @pytest.mark.asyncio
    async def test_only_subscribers_receive(self):
        mgr = WebSocketManager()
        subscriber, plain = make_ws(), make_ws()
        await mgr.connect(subscriber)
        await mgr.connect(plain)
        mgr.set_quote_subscription(subscriber, True)

        await mgr.broadcast_quote({"symbol": "SHFE.rb2505", "last_price": 3500.0})

        subscriber.send_text.assert_awaited_once()
        plain.send_text.assert_not_awaited()
        assert '"quote_update"' in subscriber.send_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_batch_quotes_type(self):
        mgr = WebSocketManager()
        ws = make_ws()
        await mgr.connect(ws)
        mgr.set_quote_subscription(ws, True)

        await mgr.broadcast_quotes({"SHFE.rb2505": {"last_price": 1.0}})

        assert '"quote_batch_update"' in ws.send_text.await_args.args[0]

    @pytest.mark.asyncio
    async def test_failed_subscriber_cleaned(self):
        mgr = WebSocketManager()
        ws = make_ws()
        ws.send_text = AsyncMock(side_effect=RuntimeError("closed"))
        await mgr.connect(ws)
        mgr.set_quote_subscription(ws, True)

        await mgr.broadcast_quote({"symbol": "x"})

        assert ws not in mgr.active_connections
        assert ws not in mgr.quote_subscriptions


@pytest.mark.unit
class TestStart:
    """事件引擎注册"""

    def test_start_registers_event_types(self):
        from qtrader.app_context import AppContext
        from qtrader.manager.api.websocket_manager import ctx

        engine = MagicMock()
        old = ctx.get(AppContext.KEY_EVENT_ENGINE)
        ctx.set(AppContext.KEY_EVENT_ENGINE, engine)
        try:
            mgr = WebSocketManager()
            mgr.start()
        finally:
            ctx.set(AppContext.KEY_EVENT_ENGINE, old)

        registered_events = {c.args[0] for c in engine.register.call_args_list}
        assert {
            "e:position.update",
            "e:order.update",
            "e:trade.created",
            "e:tick.update",
            "e:tick.batch_update",
            "e:account.update",
        } <= registered_events
