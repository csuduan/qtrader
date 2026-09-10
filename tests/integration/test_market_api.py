"""
行情与目标仓位 API 集成测试

覆盖路由模块：
- qtrader.manager.api.routes.quote（/api/quote，Trader 内存行情）
- qtrader.manager.api.routes.bars（/api/bars，BarDao 落库 K 线 + 数据服务状态）
- qtrader.manager.api.routes.contract（/api/contract，合约库查询 + 刷新）
- qtrader.manager.api.routes.target_position（/api/target-position，目标仓位比对/导入导出）

Trader 侧数据通过覆盖 mock_trading_manager 的方法构造确定返回值；
BarDao 与合约数据库分别以替身类替换。

client / mock_trading_manager 夹具来自 conftest.py。
"""

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.models.object import Exchange, TickData
from qtrader.models.po import ContractPo

# ============ 数据库查询替身 ============


class _ChainQuery:
    """模拟 SQLAlchemy Query：filter/order_by 返回自身以适配任意链长"""

    def __init__(self, all_items=None):
        self.all_items = all_items if all_items is not None else []

    def filter(self, *criteria):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.all_items


class _FakeDb:
    """模拟 Database：get_session 上下文管理器 + 会话 query"""

    def __init__(self, query: _ChainQuery):
        self.query_obj = query
        self.get_session_calls = 0

    @contextmanager
    def get_session(self):
        self.get_session_calls += 1
        yield self

    def query(self, *entities):
        return self.query_obj


# ============ 数据构造 ============


def make_tick(symbol: str = "rb2505", last: float = 3450.0) -> TickData:
    """构造真实 TickData 行情（Trader.get_quotes 的返回元素）"""
    return TickData(
        symbol=symbol,
        exchange=Exchange.SHFE,
        datetime=datetime(2026, 9, 1, 9, 0, 0),
        last_price=last,
        bid_price1=3449.0,
        ask_price1=3451.0,
        volume=12345.0,
    )


def make_contract(symbol: str = "rb2505", exchange_id: str = "SHFE") -> ContractPo:
    """构造持久化合约对象"""
    return ContractPo(
        symbol=symbol,
        exchange_id=exchange_id,
        instrument_name="螺纹钢2505",
        product_type="FUTURES",
        volume_multiple=10,
        price_tick=Decimal("1"),
        min_volume=1,
        option_strike=None,
        option_underlying=None,
        option_type=None,
        update_date="2026-09-01",
        is_active=True,
        updated_at=datetime(2026, 9, 1, 8, 0, 0),
    )


def make_bar(ts: str, close: float) -> dict:
    """构造 BarDao.query_bars 返回的 bar 字典"""
    return {
        "datetime": ts,
        "open": close - 5,
        "high": close + 5,
        "low": close - 10,
        "close": close,
        "volume": 100.0,
        "source": "history",
    }


# ============ 实时行情 API ============


@pytest.mark.integration
class TestQuoteAPI:
    """行情端点（/api/quote）"""

    def test_get_subscribed_quotes(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.get_quotes = AsyncMock(return_value=[make_tick("rb2505", 3450.0)])
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get("/api/quote", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 1
        quote = body["data"][0]
        assert quote["account_id"] == "DQ"
        assert quote["symbol"] == "rb2505"
        assert quote["last_price"] == 3450.0
        assert quote["bid_price1"] == 3449.0
        assert quote["ask_price1"] == 3451.0
        assert quote["volume"] == 12345.0
        assert quote["datetime"] == "2026-09-01T09:00:00"
        mock_trading_manager.get_trader.assert_called_once_with("DQ")

    def test_get_quotes_unknown_account_returns_empty(self, client, mock_trading_manager):
        """账户不存在时返回空列表（路由现状：非错误）"""
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.get("/api/quote", params={"account_id": "GHOST"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == []

    def test_get_quotes_without_account_returns_empty(self, client, mock_trading_manager):
        resp = client.get("/api/quote")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == []

    def test_get_quotes_error(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.get_quotes = AsyncMock(side_effect=RuntimeError("ipc boom"))
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get("/api/quote", params={"account_id": "DQ"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "获取行情列表失败" in resp.json()["message"]

    def test_subscribe(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.subscribe = AsyncMock(return_value=True)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            "/api/quote/subscribe",
            json={"account_id": "DQ", "symbol": "SHFE.rb2505"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"account_id": "DQ", "symbol": "SHFE.rb2505"}
        assert body["message"] == "已订阅 SHFE.rb2505"
        trader.subscribe.assert_awaited_once()

    def test_subscribe_missing_account(self, client):
        resp = client.post("/api/quote/subscribe", json={"symbol": "SHFE.rb2505"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400
        assert "请提供账户ID" in resp.json()["message"]

    def test_subscribe_missing_symbol(self, client):
        resp = client.post("/api/quote/subscribe", json={"account_id": "DQ"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400
        assert "请提供合约代码" in resp.json()["message"]

    def test_subscribe_unknown_account(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(
            "/api/quote/subscribe", json={"account_id": "GHOST", "symbol": "SHFE.rb2505"}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_subscribe_gateway_failure(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.subscribe = AsyncMock(return_value=False)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(
            "/api/quote/subscribe", json={"account_id": "DQ", "symbol": "SHFE.rb2505"}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "订阅 SHFE.rb2505 失败" in resp.json()["message"]


# ============ K线数据 API ============


@pytest.mark.integration
class TestBarsQueryAPI:
    """K线查询端点（GET /api/bars）"""

    def test_get_bars(self, client):
        bars = [
            make_bar("2026-09-01T09:01:00", 3450.0),
            make_bar("2026-09-01T09:02:00", 3455.0),
        ]
        dao = MagicMock()
        dao.query_bars = MagicMock(return_value=bars)
        with patch("qtrader.manager.api.routes.bars.BarDao", return_value=dao):
            resp = client.get(
                "/api/bars",
                params={
                    "symbol": "rb2505",
                    "interval": "M1",
                    "start": "2026-09-01T09:00:00",
                    "end": "2026-09-01T10:00:00",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        assert body["data"][0]["close"] == 3450.0
        assert body["data"][1]["datetime"] == "2026-09-01T09:02:00"
        assert "共2根" in body["message"]
        dao.query_bars.assert_called_once()

    def test_get_bars_missing_required_param(self, client):
        resp = client.get("/api/bars", params={"symbol": "rb2505"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400

    def test_get_bars_invalid_limit(self, client):
        """limit 低于下限 1 被拒绝"""
        resp = client.get(
            "/api/bars",
            params={
                "symbol": "rb2505",
                "start": "2026-09-01T09:00:00",
                "end": "2026-09-01T10:00:00",
                "limit": 0,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 400

    def test_get_bars_dao_error(self, client):
        dao = MagicMock()
        dao.query_bars = MagicMock(side_effect=RuntimeError("db down"))
        with patch("qtrader.manager.api.routes.bars.BarDao", return_value=dao):
            resp = client.get(
                "/api/bars",
                params={
                    "symbol": "rb2505",
                    "start": "2026-09-01T09:00:00",
                    "end": "2026-09-01T10:00:00",
                },
            )

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "查询K线失败" in resp.json()["message"]


@pytest.mark.integration
class TestBarsFeedAPI:
    """数据服务同步与状态端点（POST /api/bars/sync、GET /api/bars/feed/status）"""

    def test_sync_without_data_feed(self, client, mock_trading_manager):
        mock_trading_manager.data_feed = None

        resp = client.post("/api/bars/sync")

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 503
        assert "数据服务未启动" in body["message"]

    def test_sync_triggers_resync(self, client, mock_trading_manager):
        mock_trading_manager.data_feed = MagicMock()
        mock_trading_manager.data_feed.request_resync = MagicMock(return_value="全量同步已触发")

        resp = client.post("/api/bars/sync")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "同步已触发"
        assert body["data"] == {"message": "全量同步已触发"}
        mock_trading_manager.data_feed.request_resync.assert_called_once_with()

    def test_feed_status_disabled(self, client, mock_trading_manager):
        mock_trading_manager.data_feed = None

        resp = client.get("/api/bars/feed/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"enabled": False, "connected": False}

    def test_feed_status_enabled(self, client, mock_trading_manager):
        mock_trading_manager.data_feed = MagicMock()
        mock_trading_manager.data_feed.connected = True
        mock_trading_manager.data_feed._klines = {
            ("SHFE.rb2505", "M1"): object(),
            ("CFFEX.IM2609", "M5"): object(),
        }

        resp = client.get("/api/bars/feed/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["enabled"] is True
        assert data["connected"] is True
        assert {s["symbol"]: s["interval"] for s in data["subscriptions"]} == {
            "SHFE.rb2505": "M1",
            "CFFEX.IM2609": "M5",
        }


# ============ 合约信息 API ============


@pytest.mark.integration
class TestContractQueryAPI:
    """合约查询端点（GET /api/contract/list、GET /api/contract/exchanges）"""

    def test_list_contracts(self, client):
        db = _FakeDb(
            _ChainQuery(
                all_items=[make_contract("rb2505", "SHFE"), make_contract("IM2609", "CFFEX")]
            )
        )
        with patch("qtrader.manager.api.routes.contract.get_database", return_value=db):
            resp = client.get("/api/contract/list")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        first = body["data"][0]
        assert first["symbol"] == "rb2505"
        assert first["exchange_id"] == "SHFE"
        assert first["name"] == "螺纹钢2505"
        assert first["volume_multiple"] == 10
        assert first["price_tick"] == 1.0
        assert first["min_open_volume"] == first["min_volume"]
        assert first["update_date"] == "2026-09-01"
        assert first["updated_at"] == "2026-09-01T08:00:00"

    def test_list_contracts_without_db(self, client):
        with patch("qtrader.manager.api.routes.contract.get_database", return_value=None):
            resp = client.get("/api/contract/list")

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert "数据库未初始化" in body["message"]

    def test_list_contracts_db_error(self, client):
        with patch(
            "qtrader.manager.api.routes.contract.get_database",
            side_effect=RuntimeError("connection refused"),
        ):
            resp = client.get("/api/contract/list")

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "获取合约列表失败" in resp.json()["message"]

    def test_list_exchanges(self, client):
        db = _FakeDb(_ChainQuery(all_items=[("SHFE",), ("SHFE",), ("CFFEX",)]))
        with patch("qtrader.manager.api.routes.contract.get_database", return_value=db):
            resp = client.get("/api/contract/exchanges")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # 按交易所ID排序并正确计数
        assert body["data"] == [
            {"exchange_id": "CFFEX", "contract_count": 1},
            {"exchange_id": "SHFE", "contract_count": 2},
        ]

    def test_list_exchanges_without_db(self, client):
        with patch("qtrader.manager.api.routes.contract.get_database", return_value=None):
            resp = client.get("/api/contract/exchanges")

        assert resp.status_code == 400
        assert resp.json()["code"] == 500


@pytest.mark.integration
class TestContractRefreshAPI:
    """合约刷新端点（POST /api/contract/refresh）"""

    def test_refresh_success(self, client, mock_trading_manager):
        result = {"success": True, "results": {"DQ": {"success": True, "message": "ok"}}}
        mock_trading_manager.refresh_contracts = AsyncMock(return_value=result)

        resp = client.post("/api/contract/refresh", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == result
        assert body["message"] == "合约信息刷新成功"
        mock_trading_manager.refresh_contracts.assert_awaited_once_with("DQ")

    def test_refresh_all_accounts(self, client, mock_trading_manager):
        result = {"success": False, "results": {"DQ": {"success": True, "message": "ok"}}}
        mock_trading_manager.refresh_contracts = AsyncMock(return_value=result)

        resp = client.post("/api/contract/refresh")

        assert resp.status_code == 200
        mock_trading_manager.refresh_contracts.assert_awaited_once_with(None)

    def test_refresh_all_failed(self, client, mock_trading_manager):
        result = {
            "success": False,
            "results": {"DQ": {"success": False, "message": "Trader不存在"}},
        }
        mock_trading_manager.refresh_contracts = AsyncMock(return_value=result)

        resp = client.post("/api/contract/refresh", params={"account_id": "DQ"})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert "合约信息刷新失败" in body["message"]

    def test_refresh_exception(self, client, mock_trading_manager):
        mock_trading_manager.refresh_contracts = AsyncMock(side_effect=RuntimeError("ipc boom"))

        resp = client.post("/api/contract/refresh", params={"account_id": "DQ"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "刷新合约信息失败" in resp.json()["message"]


# ============ 目标仓位 API ============


@pytest.mark.integration
class TestTargetComparisonAPI:
    """目标仓位比对端点（GET /api/target-position）"""

    def test_get_comparison(self, client, mock_trading_manager):
        result = {
            "account_id": "DQ",
            "items": [{"symbol": "A2611", "target": 2, "current": 1}],
        }
        mock_trading_manager.get_target_comparison = AsyncMock(return_value=result)

        resp = client.get("/api/target-position", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == result
        mock_trading_manager.get_target_comparison.assert_awaited_once_with("DQ")

    def test_get_comparison_trader_offline(self, client, mock_trading_manager):
        mock_trading_manager.get_target_comparison = AsyncMock(return_value=None)

        resp = client.get("/api/target-position", params={"account_id": "DQ"})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "未连接到Trader" in body["message"]

    def test_get_comparison_error(self, client, mock_trading_manager):
        mock_trading_manager.get_target_comparison = AsyncMock(side_effect=RuntimeError("ipc boom"))

        resp = client.get("/api/target-position", params={"account_id": "DQ"})

        assert resp.status_code == 400
        assert "获取目标仓位比对失败" in resp.json()["message"]


@pytest.mark.integration
class TestTargetImportAPI:
    """目标仓位导入端点（POST /api/target-position/import）"""

    def test_import_utf8_csv(self, client, mock_trading_manager):
        csv_text = "DQ,StrategyFix_A,A2611,Sell,2\n"
        mock_trading_manager.import_target_instructions = AsyncMock(return_value={"imported": 1})

        resp = client.post(
            "/api/target-position/import",
            data={"account_id": "DQ"},
            files={"file": ("TargetPos-DQ-20260811.csv", csv_text.encode("utf-8"), "text/csv")},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "导入完成"
        assert body["data"] == {"imported": 1}
        mock_trading_manager.import_target_instructions.assert_awaited_once_with(
            "DQ", csv_text, "TargetPos-DQ-20260811.csv"
        )

    def test_import_gbk_csv(self, client, mock_trading_manager):
        """UTF-8 解码失败时回退 GBK"""
        gbk_text = "DQ,策略A,A2611,Sell,2\n"
        mock_trading_manager.import_target_instructions = AsyncMock(return_value={"imported": 1})

        resp = client.post(
            "/api/target-position/import",
            data={"account_id": "DQ"},
            files={"file": ("TargetPos-DQ-20260811.csv", gbk_text.encode("gbk"), "text/csv")},
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        # 校验传给 Manager 的文本已按 GBK 正确解码
        mock_trading_manager.import_target_instructions.assert_awaited_once_with(
            "DQ", gbk_text, "TargetPos-DQ-20260811.csv"
        )

    def test_import_error_result(self, client, mock_trading_manager):
        mock_trading_manager.import_target_instructions = AsyncMock(
            return_value={"error": "CSV列数不正确"}
        )

        resp = client.post(
            "/api/target-position/import",
            data={"account_id": "DQ"},
            files={"file": ("TargetPos-DQ-20260811.csv", b"bad", "text/csv")},
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "CSV列数不正确"

    def test_import_trader_offline(self, client, mock_trading_manager):
        mock_trading_manager.import_target_instructions = AsyncMock(return_value=None)

        resp = client.post(
            "/api/target-position/import",
            data={"account_id": "DQ"},
            files={"file": ("TargetPos-DQ-20260811.csv", b"a,b", "text/csv")},
        )

        assert resp.status_code == 400
        assert "未连接到Trader" in resp.json()["message"]


@pytest.mark.integration
class TestTargetExportAPI:
    """换仓指令与目标仓位导出端点（POST /api/target-position/export*）"""

    def test_export_with_deviation(self, client, mock_trading_manager):
        result = {"exported": 3, "file_name": "SwitchPos-DQ-20260901.csv"}
        mock_trading_manager.export_target_instructions = AsyncMock(return_value=result)

        resp = client.post("/api/target-position/export", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == result
        assert "已导出 3 条换仓指令" in body["message"]
        assert "SwitchPos-DQ-20260901.csv" in body["message"]

    def test_export_without_deviation(self, client, mock_trading_manager):
        mock_trading_manager.export_target_instructions = AsyncMock(return_value={"exported": 0})

        resp = client.post("/api/target-position/export", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "无偏差，未生成指令文件" in body["message"]

    def test_export_error_result(self, client, mock_trading_manager):
        mock_trading_manager.export_target_instructions = AsyncMock(
            return_value={"error": "Trader离线"}
        )

        resp = client.post("/api/target-position/export", params={"account_id": "DQ"})

        assert resp.status_code == 400
        assert resp.json()["message"] == "Trader离线"

    def test_export_trader_offline(self, client, mock_trading_manager):
        mock_trading_manager.export_target_instructions = AsyncMock(return_value=None)

        resp = client.post("/api/target-position/export", params={"account_id": "DQ"})

        assert resp.status_code == 400
        assert "未连接到Trader" in resp.json()["message"]

    def test_export_positions(self, client, mock_trading_manager):
        result = {"exported": 2, "file_name": "TargetPos-DQ-20260901.csv"}
        mock_trading_manager.export_target_positions = AsyncMock(return_value=result)

        resp = client.post("/api/target-position/export-positions", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == result
        assert "已导出 2 条目标仓位" in body["message"]
        # 未显式传 strategy_id 时默认 manual
        mock_trading_manager.export_target_positions.assert_awaited_once_with("DQ", "manual")

    def test_export_positions_with_strategy(self, client, mock_trading_manager):
        mock_trading_manager.export_target_positions = AsyncMock(
            return_value={"exported": 1, "file_name": "f.csv"}
        )

        resp = client.post(
            "/api/target-position/export-positions",
            params={"account_id": "DQ", "strategy_id": "StrategyFix_A"},
        )

        assert resp.status_code == 200
        mock_trading_manager.export_target_positions.assert_awaited_once_with("DQ", "StrategyFix_A")

    def test_export_positions_no_position(self, client, mock_trading_manager):
        mock_trading_manager.export_target_positions = AsyncMock(return_value={"exported": 0})

        resp = client.post("/api/target-position/export-positions", params={"account_id": "DQ"})

        assert resp.status_code == 200
        assert "无持仓，未导出目标仓位文件" in resp.json()["message"]

    def test_export_positions_trader_offline(self, client, mock_trading_manager):
        mock_trading_manager.export_target_positions = AsyncMock(return_value=None)

        resp = client.post("/api/target-position/export-positions", params={"account_id": "DQ"})

        assert resp.status_code == 400
        assert "未连接到Trader" in resp.json()["message"]


@pytest.mark.integration
class TestTargetUpdateAPI:
    """目标手数更新端点（POST /api/target-position/update）"""

    def test_update_target_volume(self, client, mock_trading_manager):
        mock_trading_manager.update_target_volume = AsyncMock(
            return_value={"updated": True, "target_volume": 5}
        )

        resp = client.post(
            "/api/target-position/update",
            params={"account_id": "DQ"},
            json={"symbol": "A2611", "side": "LONG", "target_volume": 5},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "目标手数已更新"
        assert body["data"] == {"updated": True, "target_volume": 5}
        mock_trading_manager.update_target_volume.assert_awaited_once_with("DQ", "A2611", "LONG", 5)

    def test_update_target_volume_error(self, client, mock_trading_manager):
        mock_trading_manager.update_target_volume = AsyncMock(return_value={"error": "侧别无效"})

        resp = client.post(
            "/api/target-position/update",
            params={"account_id": "DQ"},
            json={"symbol": "A2611", "side": "WRONG", "target_volume": 5},
        )

        assert resp.status_code == 400
        assert resp.json()["message"] == "侧别无效"

    def test_update_target_volume_trader_offline(self, client, mock_trading_manager):
        mock_trading_manager.update_target_volume = AsyncMock(return_value=None)

        resp = client.post(
            "/api/target-position/update",
            params={"account_id": "DQ"},
            json={"symbol": "A2611", "side": "LONG"},
        )

        assert resp.status_code == 400
        assert "未连接到Trader" in resp.json()["message"]
