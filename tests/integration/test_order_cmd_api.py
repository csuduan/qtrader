"""
报单指令 API 集成测试

覆盖路由 qtrader.manager.api.routes.order_cmd（前缀 /api/order-cmd）。
走完整 FastAPI 栈，TradingManager / TraderProxy 全程 mock。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

ACCOUNT = "DQ"
BASE = "/api/order-cmd"


def make_trader() -> MagicMock:
    """构造 send_request 已配置的 TraderProxy mock"""
    trader = MagicMock()
    trader.send_request = AsyncMock(return_value={"success": True, "cmd_id": "cmd_9"})
    return trader


def make_cmd_payload(cmd_id: str, started_at: str, status: str = "RUNNING") -> dict:
    """Trader 进程返回的报单指令状态条目"""
    return {
        "cmd_id": cmd_id,
        "status": status,
        "symbol": "SHFE.rb2505",
        "filled_volume": 1,
        "volume": 3,
        "direction": "BUY",
        "offset": "OPEN",
        "limit_price": 3450.0,
        "source": "手动报单",
        "started_at": started_at,
        "finished_at": None,
        "total_orders": 2,
        "finish_reason": "",
    }


@pytest.mark.integration
class TestGetOrderCmdsStatus:
    """获取报单指令状态 GET /api/order-cmd"""

    def test_missing_account_id(self, client):
        resp = client.get(BASE)

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 400
        assert body["message"] == "请提供账户ID"

    def test_empty_result_returns_empty_list(self, client, mock_trading_manager):
        mock_trading_manager.get_order_cmds_status = AsyncMock(return_value=None)

        resp = client.get(BASE, params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == []
        mock_trading_manager.get_order_cmds_status.assert_awaited_once_with(ACCOUNT, None)

    def test_result_sorted_by_started_at_desc(self, client, mock_trading_manager):
        mock_trading_manager.get_order_cmds_status = AsyncMock(
            return_value=[
                make_cmd_payload("c_early", "2026-09-01T10:00:00"),
                make_cmd_payload("c_late", "2026-09-01T11:00:00", status="FINISHED"),
            ]
        )

        resp = client.get(BASE, params={"account_id": ACCOUNT, "status": "active"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert [item["cmd_id"] for item in data] == ["c_late", "c_early"]
        first = data[0]
        assert first["status"] == "FINISHED"
        assert first["symbol"] == "SHFE.rb2505"
        assert first["direction"] == "BUY"
        assert first["offset"] == "OPEN"
        assert first["limit_price"] == 3450.0
        assert first["source"] == "手动报单"
        assert first["volume"] == 3
        assert first["filled_volume"] == 1
        assert first["total_orders"] == 2
        assert first["started_at"] == "2026-09-01T11:00:00"
        assert first["finished_at"] is None
        mock_trading_manager.get_order_cmds_status.assert_awaited_once_with(ACCOUNT, "active")

    def test_backend_error(self, client, mock_trading_manager):
        mock_trading_manager.get_order_cmds_status = AsyncMock(side_effect=RuntimeError("boom"))

        resp = client.get(BASE, params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert "获取报单指令失败" in body["message"]
        assert "boom" in body["message"]


@pytest.mark.integration
class TestSendOrderCmd:
    """发送账户级报单指令 POST /api/order-cmd"""

    def payload(self, **overrides) -> dict:
        base = {
            "symbol": "SHFE.rb2505",
            "direction": "SELL",
            "offset": "CLOSE",
            "volume": 2,
            "price": 3450.5,
        }
        base.update(overrides)
        return base

    def test_send_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(BASE, params={"account_id": ACCOUNT}, json=self.payload())

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "报单指令已发送"
        assert body["data"] == {"cmd_id": "cmd_9"}
        trader.send_request.assert_awaited_once_with(
            "send_order_cmd",
            {
                "order_cmd": {
                    "symbol": "SHFE.rb2505",
                    "direction": "SELL",
                    "offset": "CLOSE",
                    "volume": 2,
                    "price": 3450.5,
                    "source": None,
                }
            },
            timeout=10.0,
        )

    def test_send_volume_string_coerced(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            BASE, params={"account_id": ACCOUNT}, json=self.payload(volume="2", price="3450")
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        trader.send_request.assert_awaited_once_with(
            "send_order_cmd",
            {
                "order_cmd": {
                    "symbol": "SHFE.rb2505",
                    "direction": "SELL",
                    "offset": "CLOSE",
                    "volume": 2,
                    "price": 3450.0,
                    "source": None,
                }
            },
            timeout=10.0,
        )

    def test_send_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(BASE, params={"account_id": ACCOUNT}, json=self.payload())

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert f"账户 [{ACCOUNT}] 不存在" == body["message"]

    def test_send_missing_required_params(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            BASE,
            params={"account_id": ACCOUNT},
            json={"symbol": "SHFE.rb2505", "direction": "BUY"},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "缺少必要参数" in body["message"]

    def test_send_invalid_direction(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            BASE,
            params={"account_id": ACCOUNT},
            json=self.payload(direction="WRONG"),
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "direction 必须是 BUY 或 SELL"

    def test_send_invalid_offset(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            BASE,
            params={"account_id": ACCOUNT},
            json=self.payload(offset="FORCE"),
        )

        assert resp.status_code == 400
        assert "offset 必须是" in resp.json()["message"]

    def test_send_volume_not_positive(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            BASE,
            params={"account_id": ACCOUNT},
            json=self.payload(volume=0),
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "volume 必须大于0"

    def test_send_volume_not_integer(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            BASE,
            params={"account_id": ACCOUNT},
            json=self.payload(volume="abc"),
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "volume 必须是整数"

    def test_send_price_not_number(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            BASE,
            params={"account_id": ACCOUNT},
            json=self.payload(price="abc"),
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "price 必须是数字"

    def test_send_rejected_by_trader(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value={"success": False, "message": "资金不足"})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(BASE, params={"account_id": ACCOUNT}, json=self.payload())

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "资金不足"

    def test_send_no_response(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value=None)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(BASE, params={"account_id": ACCOUNT}, json=self.payload())

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "发送报单指令失败"


@pytest.mark.integration
class TestCancelOrderCmd:
    """强制取消报单指令 POST /api/order-cmd/{cmd_id}/cancel"""

    def test_cancel_success(self, client, mock_trading_manager):
        mock_trading_manager.cancel_order_cmd = AsyncMock(return_value={"success": True})

        resp = client.post(f"{BASE}/cmd_9/cancel", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "取消指令成功"
        mock_trading_manager.cancel_order_cmd.assert_awaited_once_with(ACCOUNT, "cmd_9")

    def test_cancel_missing_account_id(self, client):
        resp = client.post(f"{BASE}/cmd_9/cancel")

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 400
        assert body["message"] == "请提供账户ID"

    def test_cancel_no_result(self, client, mock_trading_manager):
        mock_trading_manager.cancel_order_cmd = AsyncMock(return_value=None)

        resp = client.post(f"{BASE}/cmd_9/cancel", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "取消指令失败"

    def test_cancel_failed_with_reason(self, client, mock_trading_manager):
        mock_trading_manager.cancel_order_cmd = AsyncMock(
            return_value={"success": False, "message": "指令已结束"}
        )

        resp = client.post(f"{BASE}/cmd_9/cancel", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 400
        assert body["message"] == "指令已结束"

    def test_cancel_backend_error(self, client, mock_trading_manager):
        mock_trading_manager.cancel_order_cmd = AsyncMock(side_effect=RuntimeError("boom"))

        resp = client.post(f"{BASE}/cmd_9/cancel", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert "取消报单指令失败" in body["message"]
