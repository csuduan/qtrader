"""
策略管理 API 集成测试

覆盖路由 qtrader.manager.api.routes.strategy（前缀 /api/strategies）。
走完整 FastAPI 栈（中间件 + 路由 + 依赖注入），TradingManager / TraderProxy 全程 mock，
断言使用确定性数据。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.manager.api.schemas import StrategyRes

ACCOUNT = "DQ"
STRATEGY = "rsi_1"
BASE = "/api/strategies"


def make_trader() -> MagicMock:
    """构造各策略操作方法均已配置为成功的 TraderProxy mock"""
    trader = MagicMock()
    trader.update_strategy_params = AsyncMock(return_value={"success": True})
    trader.clear_strategy_signal = AsyncMock(return_value={"success": True})
    trader.update_strategy_signal = AsyncMock(return_value={"success": True})
    trader.update_strategy_position = AsyncMock(return_value={"success": True})
    trader.set_strategy_trading_status = AsyncMock(
        return_value={"success": True, "data": {"opening_paused": True}}
    )
    trader.enable_strategy = AsyncMock(return_value={"success": True})
    trader.disable_strategy = AsyncMock(return_value={"success": True})
    trader.init_strategy = AsyncMock(return_value={"success": True})
    trader.get_strategy_order_cmds = AsyncMock(return_value=[{"cmd_id": "c1"}])
    trader.send_request = AsyncMock(return_value={"success": True})
    return trader


def make_strategy_res() -> StrategyRes:
    """策略列表条目（真实 Pydantic 模型）"""
    return StrategyRes(
        strategy_id=STRATEGY,
        enabled=True,
        inited=True,
        symbol="SHFE.rb2505",
        trading_status="RUNNING",
    )


def make_strategy_detail() -> dict:
    """Trader 进程 get_strategy 返回的策略详情 dict"""
    return {
        "strategy_id": STRATEGY,
        "enabled": True,
        "inited": True,
        "active": True,
        "symbol": "SHFE.rb2505",
        "config": {"params_file": "params/rsi.yaml"},
        "params": {
            "symbol": "SHFE.rb2505",
            "volume_per_trade": 2,
            "take_profit_pct": 0.02,
            "stop_loss_pct": 0.01,
        },
    }


@pytest.mark.integration
class TestListStrategies:
    """获取策略列表 GET /api/strategies"""

    def test_list_success(self, client, mock_trading_manager):
        mock_trading_manager.list_strategies = AsyncMock(
            return_value=[make_strategy_res(), StrategyRes(strategy_id="dual_ma")]
        )

        resp = client.get(BASE, params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        assert body["data"][0]["strategy_id"] == STRATEGY
        assert body["data"][0]["symbol"] == "SHFE.rb2505"
        assert body["data"][0]["enabled"] is True
        assert body["data"][1]["strategy_id"] == "dual_ma"
        mock_trading_manager.list_strategies.assert_awaited_once_with(ACCOUNT)

    def test_list_backend_error(self, client, mock_trading_manager):
        mock_trading_manager.list_strategies = AsyncMock(side_effect=RuntimeError("boom"))

        resp = client.get(BASE, params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "获取策略列表失败" in body["message"]
        assert "boom" in body["message"]


@pytest.mark.integration
class TestGetStrategy:
    """获取指定策略 GET /api/strategies/{strategy_id}"""

    def test_get_success(self, client, mock_trading_manager):
        mock_trading_manager.get_strategy = AsyncMock(return_value=make_strategy_detail())

        resp = client.get(f"{BASE}/{STRATEGY}", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["strategy_id"] == STRATEGY
        assert body["data"]["params"]["volume_per_trade"] == 2
        mock_trading_manager.get_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)

    def test_get_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_strategy = AsyncMock(return_value=None)

        resp = client.get(f"{BASE}/ghost", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert "策略不存在" in body["message"]


@pytest.mark.integration
class TestStartStopStrategy:
    """启停单个策略 POST /api/strategies/{strategy_id}/start|stop"""

    def test_start_success(self, client, mock_trading_manager):
        mock_trading_manager.start_strategy = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/{STRATEGY}/start", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 启动成功"
        mock_trading_manager.start_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)

    def test_start_failed(self, client, mock_trading_manager):
        mock_trading_manager.start_strategy = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/{STRATEGY}/start", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400
        assert "启动策略失败" in resp.json()["message"]

    def test_stop_success(self, client, mock_trading_manager):
        mock_trading_manager.stop_strategy = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/{STRATEGY}/stop", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 停止成功"
        mock_trading_manager.stop_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)

    def test_stop_failed(self, client, mock_trading_manager):
        mock_trading_manager.stop_strategy = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/{STRATEGY}/stop", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400
        assert "停止策略失败" in resp.json()["message"]


@pytest.mark.integration
class TestStartStopAllStrategies:
    """全量启停 POST /api/strategies/start-all|stop-all"""

    def test_start_all_success(self, client, mock_trading_manager):
        mock_trading_manager.start_all_strategies = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/start-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "已启动所有策略"
        mock_trading_manager.start_all_strategies.assert_awaited_once_with(ACCOUNT)

    def test_start_all_failed(self, client, mock_trading_manager):
        mock_trading_manager.start_all_strategies = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/start-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 9999
        assert resp.json()["message"] == "启动策略失败"

    def test_stop_all_success(self, client, mock_trading_manager):
        mock_trading_manager.stop_all_strategies = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/stop-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "已停止所有策略"

    def test_stop_all_failed(self, client, mock_trading_manager):
        mock_trading_manager.stop_all_strategies = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/stop-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 9999
        assert resp.json()["message"] == "停止策略失败"


@pytest.mark.integration
class TestBatchOperateStrategies:
    """批量操作策略 POST /api/strategies/batch"""

    def test_batch_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            BASE + "/batch",
            params={"account_id": ACCOUNT},
            json={"strategy_ids": [STRATEGY], "operation": "start"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404
        assert "未找到或未连接" in resp.json()["message"]

    def test_batch_start_mixed_result(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())
        mock_trading_manager.start_strategy = AsyncMock(side_effect=[True, False])

        resp = client.post(
            BASE + "/batch",
            params={"account_id": ACCOUNT},
            json={"strategy_ids": ["s1", "s2"], "operation": "start"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["success"] == ["s1"]
        assert body["data"]["failed"] == [{"id": "s2", "reason": "操作失败"}]
        assert body["message"] == "批量start完成: 成功1个, 失败1个"

    def test_batch_stop(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())
        mock_trading_manager.stop_strategy = AsyncMock(return_value=True)

        resp = client.post(
            BASE + "/batch",
            params={"account_id": ACCOUNT},
            json={"strategy_ids": [STRATEGY], "operation": "stop"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["success"] == [STRATEGY]
        mock_trading_manager.stop_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)

    def test_batch_restart(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())
        mock_trading_manager.stop_strategy = AsyncMock(return_value=True)
        mock_trading_manager.start_strategy = AsyncMock(return_value=True)

        with patch(
            "qtrader.manager.api.routes.strategy.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            resp = client.post(
                BASE + "/batch",
                params={"account_id": ACCOUNT},
                json={"strategy_ids": [STRATEGY], "operation": "restart"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["success"] == [STRATEGY]
        mock_sleep.assert_awaited_once_with(0.5)
        mock_trading_manager.stop_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)
        mock_trading_manager.start_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)

    def test_batch_unsupported_operation_recorded_as_failed(self, client, mock_trading_manager):
        """未知操作类型不会中断请求，而是记入 failed 列表"""
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            BASE + "/batch",
            params={"account_id": ACCOUNT},
            json={"strategy_ids": [STRATEGY], "operation": "unknown"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["success"] == []
        assert body["data"]["failed"][0]["id"] == STRATEGY
        assert "不支持的操作类型" in body["data"]["failed"][0]["reason"]


@pytest.mark.integration
class TestUpdateStrategyParams:
    """更新策略参数 PATCH /api/strategies/{strategy_id}"""

    def test_update_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.patch(
            f"{BASE}/{STRATEGY}",
            params={"account_id": ACCOUNT},
            json={"params": {"take_profit_pct": 0.05}, "restart": False},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 参数更新成功"
        trader.update_strategy_params.assert_awaited_once_with(STRATEGY, {"take_profit_pct": 0.05})

    def test_update_rejected_by_trader(self, client, mock_trading_manager):
        trader = make_trader()
        trader.update_strategy_params = AsyncMock(
            return_value={"success": False, "message": "参数非法"}
        )
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.patch(
            f"{BASE}/{STRATEGY}",
            params={"account_id": ACCOUNT},
            json={"params": {"volume_per_trade": -1}},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "参数非法"

    def test_update_with_restart(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)
        mock_trading_manager.stop_strategy = AsyncMock(return_value=True)
        mock_trading_manager.start_strategy = AsyncMock(return_value=True)

        with patch("qtrader.manager.api.routes.strategy.asyncio.sleep", new_callable=AsyncMock):
            resp = client.patch(
                f"{BASE}/{STRATEGY}",
                params={"account_id": ACCOUNT},
                json={"params": {"stop_loss_pct": 0.02}, "restart": True},
            )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        mock_trading_manager.stop_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)
        mock_trading_manager.start_strategy.assert_awaited_once_with(ACCOUNT, STRATEGY)

    def test_update_without_params_skips_trader_call(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.patch(f"{BASE}/{STRATEGY}", params={"account_id": ACCOUNT}, json={})

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        trader.update_strategy_params.assert_not_awaited()

    def test_update_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.patch(
            f"{BASE}/{STRATEGY}",
            params={"account_id": ACCOUNT},
            json={"params": {"stop_loss_pct": 0.02}},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404
        assert "未找到或未连接" in resp.json()["message"]


@pytest.mark.integration
class TestUpdateStrategySignal:
    """更新策略信号 POST /api/strategies/{strategy_id}/update-signal"""

    def test_clear_signal_when_body_missing(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/{STRATEGY}/update-signal", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 信号已清除"
        trader.clear_strategy_signal.assert_awaited_once_with(STRATEGY)
        trader.update_strategy_signal.assert_not_awaited()

    def test_clear_signal_when_side_zero(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-signal",
            params={"account_id": ACCOUNT},
            json={"side": 0, "price": 3450},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == f"策略 {STRATEGY} 信号已清除"
        trader.clear_strategy_signal.assert_awaited_once_with(STRATEGY)

    def test_update_signal(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)
        signal = {"side": 1, "price": 3450}

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-signal", params={"account_id": ACCOUNT}, json=signal
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 信号更新成功"
        trader.update_strategy_signal.assert_awaited_once_with(STRATEGY, signal)
        trader.clear_strategy_signal.assert_not_awaited()

    def test_update_signal_rejected(self, client, mock_trading_manager):
        trader = make_trader()
        trader.update_strategy_signal = AsyncMock(
            return_value={"success": False, "message": "信号无效"}
        )
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-signal",
            params={"account_id": ACCOUNT},
            json={"side": 1},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "信号无效"

    def test_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(f"{BASE}/{STRATEGY}/update-signal", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404
        assert "未找到或未连接" in resp.json()["message"]


@pytest.mark.integration
class TestUpdateStrategyPosition:
    """更新策略持仓 POST /api/strategies/{strategy_id}/update-position"""

    def test_update_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)
        position = {"pos_long": 2, "pos_short": 0, "pos_price": 3450.0}

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-position",
            params={"account_id": ACCOUNT},
            json=position,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 持仓更新成功"
        trader.update_strategy_position.assert_awaited_once_with(STRATEGY, position)

    def test_update_rejected(self, client, mock_trading_manager):
        trader = make_trader()
        trader.update_strategy_position = AsyncMock(
            return_value={"success": False, "message": "持仓校验失败"}
        )
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-position",
            params={"account_id": ACCOUNT},
            json={"pos_long": 2},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "持仓校验失败"

    def test_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-position",
            params={"account_id": ACCOUNT},
            json={"pos_long": 2},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestStrategyStatus:
    """策略详细状态 GET /api/strategies/{strategy_id}/status（直接返回模型，无统一包装）"""

    def test_get_status(self, client, mock_trading_manager):
        mock_trading_manager.get_strategy = AsyncMock(
            return_value={
                "strategy_id": STRATEGY,
                "active": True,
                "enabled": True,
                "inited": True,
                "trade_count": 7,
                "total_pnl": 1234.5,
            }
        )

        resp = client.get(f"{BASE}/{STRATEGY}/status", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["strategy_id"] == STRATEGY
        assert body["active"] is True
        assert body["trade_count"] == 7
        assert body["total_pnl"] == 1234.5
        assert "updated_at" in body

    def test_status_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_strategy = AsyncMock(return_value=None)

        resp = client.get(f"{BASE}/ghost/status", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert "策略不存在" in body["message"]


@pytest.mark.integration
class TestStrategyParams:
    """策略参数展示 GET /api/strategies/{strategy_id}/params"""

    def test_get_params_with_summary(self, client, mock_trading_manager):
        mock_trading_manager.get_strategy = AsyncMock(return_value=make_strategy_detail())

        resp = client.get(f"{BASE}/{STRATEGY}/params", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["strategy_id"] == STRATEGY
        assert data["params_file"] == "params/rsi.yaml"
        assert data["params"]["volume_per_trade"] == 2
        assert data["summary"] == {
            "symbol": "SHFE.rb2505",
            "volume": 2,
            "tp": 0.02,
            "sl": 0.01,
        }

    def test_params_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_strategy = AsyncMock(return_value=None)

        resp = client.get(f"{BASE}/ghost/params", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestReplayAllStrategies:
    """回播所有策略行情 POST /api/strategies/replay-all"""

    def test_replay_success(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value={"success": True, "replayed_count": 3})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/replay-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["replayed_count"] == 3
        trader.send_request.assert_awaited_once_with("replay_all_strategies", {}, timeout=120.0)

    def test_replay_no_response(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value=None)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/replay-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "回播请求失败：无响应"

    def test_replay_failed_with_message(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value={"success": False, "message": "行情数据缺失"})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/replay-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["message"] == "行情数据缺失"

    def test_replay_non_dict_response(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value="boom")
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/replay-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "回播失败"

    def test_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(f"{BASE}/replay-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestSetStrategyTradingStatus:
    """设置策略交易状态 POST /api/strategies/{strategy_id}/trading-status"""

    def test_set_both_flags(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/trading-status",
            params={"account_id": ACCOUNT},
            json={"opening_paused": True, "closing_paused": False},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 开仓已暂停, 平仓已恢复成功"
        assert body["data"] == {"opening_paused": True}
        trader.set_strategy_trading_status.assert_awaited_once_with(
            STRATEGY, {"opening_paused": True, "closing_paused": False}
        )

    def test_set_opening_only(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/trading-status",
            params={"account_id": ACCOUNT},
            json={"opening_paused": True},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == f"策略 {STRATEGY} 开仓已暂停成功"

    def test_set_rejected(self, client, mock_trading_manager):
        trader = make_trader()
        trader.set_strategy_trading_status = AsyncMock(
            return_value={"success": False, "message": "策略运行中"}
        )
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/trading-status",
            params={"account_id": ACCOUNT},
            json={"closing_paused": True},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "策略运行中"

    def test_trader_not_found_swallowed_as_9999(self, client, mock_trading_manager):
        """该端点未单独放行 HTTPException，404 被通用 except 转成业务码 9999"""
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            f"{BASE}/{STRATEGY}/trading-status",
            params={"account_id": ACCOUNT},
            json={"opening_paused": True},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "未找到或未连接" in body["message"]


@pytest.mark.integration
class TestEnableDisableInitStrategy:
    """启用/禁用/初始化策略 POST /api/strategies/{strategy_id}/enable|disable|init"""

    def test_enable_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/{STRATEGY}/enable", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 启用成功"
        trader.enable_strategy.assert_awaited_once_with(STRATEGY)

    def test_enable_rejected(self, client, mock_trading_manager):
        trader = make_trader()
        trader.enable_strategy = AsyncMock(return_value={"success": False, "message": "已启用"})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/{STRATEGY}/enable", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["message"] == "已启用"

    def test_disable_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/{STRATEGY}/disable", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        assert resp.json()["message"] == f"策略 {STRATEGY} 禁用成功"
        trader.disable_strategy.assert_awaited_once_with(STRATEGY)

    def test_disable_rejected(self, client, mock_trading_manager):
        trader = make_trader()
        trader.disable_strategy = AsyncMock(return_value={"success": False})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/{STRATEGY}/disable", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "禁用策略失败"

    def test_init_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/{STRATEGY}/init", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        assert resp.json()["message"] == f"策略 {STRATEGY} 初始化成功"
        trader.init_strategy.assert_awaited_once_with(STRATEGY)

    def test_init_rejected(self, client, mock_trading_manager):
        trader = make_trader()
        trader.init_strategy = AsyncMock(return_value={"success": False, "message": "网关未连接"})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/{STRATEGY}/init", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["message"] == "网关未连接"


@pytest.mark.integration
class TestStrategyOrderCmds:
    """策略报单指令历史 GET /api/strategies/{strategy_id}/order-cmds"""

    def test_get_order_cmds(self, client, mock_trading_manager):
        trader = make_trader()
        trader.get_strategy_order_cmds = AsyncMock(
            return_value=[{"cmd_id": "c1", "status": "FINISHED"}]
        )
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get(f"{BASE}/{STRATEGY}/order-cmds", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == [{"cmd_id": "c1", "status": "FINISHED"}]
        trader.get_strategy_order_cmds.assert_awaited_once_with(STRATEGY, None)

    def test_get_order_cmds_with_status_filter(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get(
            f"{BASE}/{STRATEGY}/order-cmds",
            params={"account_id": ACCOUNT, "status": "active"},
        )

        assert resp.status_code == 200
        trader.get_strategy_order_cmds.assert_awaited_once_with(STRATEGY, "active")

    def test_get_order_cmds_none(self, client, mock_trading_manager):
        trader = make_trader()
        trader.get_strategy_order_cmds = AsyncMock(return_value=None)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get(f"{BASE}/{STRATEGY}/order-cmds", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "获取报单指令失败"

    def test_trader_not_found_swallowed_as_9999(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.get(f"{BASE}/{STRATEGY}/order-cmds", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "未找到或未连接" in body["message"]


@pytest.mark.integration
class TestSendStrategyOrderCmd:
    """发送策略报单指令 POST /api/strategies/{strategy_id}/send-order-cmd"""

    def test_send_success(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value={"success": True})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "SELL",
                "offset": "CLOSE",
                "volume": 2,
                "price": 3450.5,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 报单指令已发送"
        assert body["data"]["cmd_id"]

        trader.send_request.assert_awaited_once()
        args, kwargs = trader.send_request.await_args
        assert args[0] == "send_strategy_order_cmd"
        payload = args[1]
        assert payload["strategy_id"] == STRATEGY
        cmd = payload["order_cmd"]
        assert cmd["symbol"] == "SHFE.rb2505"
        assert cmd["direction"] == "SELL"
        assert cmd["offset"] == "CLOSE"
        assert cmd["volume"] == 2
        assert cmd["source"] == f"手动-{STRATEGY}"
        # 限价单 price 必须透传，Trader 侧据此判断市价/限价
        assert cmd["price"] == 3450.5
        assert kwargs == {"timeout": 10.0}

    def test_send_missing_params(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
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
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "WRONG",
                "offset": "OPEN",
                "volume": 1,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "direction 必须是 BUY 或 SELL"

    def test_send_invalid_offset(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "FORCE",
                "volume": 1,
            },
        )

        assert resp.status_code == 400
        assert "offset 必须是" in resp.json()["message"]

    def test_send_volume_not_positive(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 0,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "volume 必须大于0"

    def test_send_volume_not_integer(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": "abc",
            },
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "volume 必须是整数"

    def test_send_price_not_number(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
                "price": "abc",
            },
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "price 必须是数字"

    def test_send_rejected_by_trader(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value={"success": False, "message": "禁止下单"})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "禁止下单"

    def test_send_no_response(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value=None)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
            },
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "发送报单指令失败"

    def test_trader_not_found_swallowed_as_9999(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            f"{BASE}/{STRATEGY}/send-order-cmd",
            params={"account_id": ACCOUNT},
            json={
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
            },
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "未找到或未连接" in body["message"]


@pytest.mark.integration
class TestUpdateStrategyPositionDetail:
    """更新策略持仓详情 POST /api/strategies/{strategy_id}/update-position-detail"""

    def test_update_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)
        position = {
            "symbol": "SHFE.rb2505",
            "pos_long_td": 2,
            "pos_long_yd": 0,
            "hold_price_long": 3450.0,
        }

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-position-detail",
            params={"account_id": ACCOUNT},
            json=position,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} 持仓更新成功"
        trader.send_request.assert_awaited_once_with(
            "update_strategy_position_detail",
            {"strategy_id": STRATEGY, "position": position},
            timeout=10.0,
        )

    def test_update_failed(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value=None)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-position-detail",
            params={"account_id": ACCOUNT},
            json={"symbol": "SHFE.rb2505", "pos_long_td": 2},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "更新持仓失败"

    def test_trader_not_found_swallowed_as_9999(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            f"{BASE}/{STRATEGY}/update-position-detail",
            params={"account_id": ACCOUNT},
            json={"symbol": "SHFE.rb2505", "pos_long_td": 2},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 9999


@pytest.mark.integration
class TestDeleteStrategyPosition:
    """删除策略持仓 POST /api/strategies/{strategy_id}/delete-position"""

    def test_delete_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/delete-position",
            params={"account_id": ACCOUNT},
            json={"symbol": "SHFE.rb2505"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == f"策略 {STRATEGY} SHFE.rb2505 持仓已删除"
        trader.send_request.assert_awaited_once_with(
            "delete_strategy_position",
            {"strategy_id": STRATEGY, "symbol": "SHFE.rb2505"},
            timeout=10.0,
        )

    def test_delete_missing_symbol(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.post(
            f"{BASE}/{STRATEGY}/delete-position", params={"account_id": ACCOUNT}, json={}
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "合约代码不能为空"

    def test_delete_failed(self, client, mock_trading_manager):
        trader = make_trader()
        trader.send_request = AsyncMock(return_value={"success": False, "message": "持仓非零"})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            f"{BASE}/{STRATEGY}/delete-position",
            params={"account_id": ACCOUNT},
            json={"symbol": "SHFE.rb2505"},
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "持仓非零"

    def test_trader_not_found_swallowed_as_9999(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            f"{BASE}/{STRATEGY}/delete-position",
            params={"account_id": ACCOUNT},
            json={"symbol": "SHFE.rb2505"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 9999
