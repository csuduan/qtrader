"""TqContractFetcher 单元测试：主力打标逻辑、保证金/交易时间解析与订阅"""

import math
from unittest.mock import MagicMock

import pytest

from qtrader.manager.tq_contract_fetcher import (
    TqContractFetcher,
    parse_exchange_margin,
    parse_trading_time,
)

pytestmark = [pytest.mark.unit]


class TestParseExchangeMargin:
    def test_normal_value_rounded(self):
        """正常数值保留2位小数"""
        assert parse_exchange_margin(8112.456) == 8112.46

    def test_nan_returns_none(self):
        """NaN 返回 None（天勤缺失数据以 NaN 表示）"""
        assert parse_exchange_margin(float("nan")) is None

    def test_none_returns_none(self):
        assert parse_exchange_margin(None) is None

    def test_invalid_string_returns_none(self):
        assert parse_exchange_margin("abc") is None

    def test_numeric_string_parsed(self):
        assert parse_exchange_margin("8112.4") == 8112.4

    def test_pandas_nan(self):
        """pandas 列中的 NaN 值同样返回 None"""
        assert parse_exchange_margin(math.nan) is None


class TestParseTradingTime:
    def test_day_sessions(self):
        """白盘多时段拼接为展示串（截掉秒位）"""
        value = [["09:00:00", "10:15:00"], ["10:30:00", "11:30:00"], ["13:30:00", "15:00:00"]]
        assert parse_trading_time(value) == "09:00-10:15,10:30-11:30,13:30-15:00"

    def test_night_session_crossing_midnight(self):
        """跨零点夜盘保留天勤原始表示（25:00 即次日1点）"""
        assert parse_trading_time([["21:00:00", "25:00:00"]]) == "21:00-25:00"

    def test_none_returns_none(self):
        """无夜盘（None）返回 None"""
        assert parse_trading_time(None) is None

    def test_empty_returns_none(self):
        assert parse_trading_time([]) is None


def _contracts() -> list[dict]:
    return [
        {"symbol": "rb2701", "exchange_id": "SHFE"},
        {"symbol": "rb2705", "exchange_id": "SHFE"},
        {"symbol": "IC2609", "exchange_id": "CFFEX"},
        {"symbol": "T2612", "exchange_id": "CFFEX"},
    ]


class TestMarkDominantContracts:
    def test_marks_current_dominant(self):
        """主力合约（underlying_symbol 命中）标记 is_main=True，其余 False"""
        api = MagicMock()

        def get_quote_list(symbols: list):
            m = {
                "KQ.m@CFFEX.IC": MagicMock(underlying_symbol="CFFEX.IC2609"),
                "KQ.m@CFFEX.T": MagicMock(underlying_symbol="CFFEX.T2612"),
                "KQ.m@SHFE.rb": MagicMock(underlying_symbol="SHFE.rb2701"),
            }
            return [m[s] for s in symbols]

        api.get_quote_list.side_effect = get_quote_list
        contracts = _contracts()
        TqContractFetcher._mark_dominant_contracts(api, contracts)

        assert [c["is_main"] for c in contracts] == [True, False, True, True]

    def test_underlying_without_exchange_prefix(self):
        """underlying_symbol 无交易所前缀时按裸代码匹配"""
        api = MagicMock()
        api.get_quote_list.return_value = [MagicMock(underlying_symbol="rb2705")]
        contracts = _contracts()[:2]
        TqContractFetcher._mark_dominant_contracts(api, contracts)

        assert contracts[1]["is_main"] is True
        assert contracts[0]["is_main"] is False

    def test_single_batch_query_per_product(self):
        """全部品种合并为一次批量订阅，同品种不重复"""
        api = MagicMock()
        api.get_quote_list.return_value = [MagicMock(underlying_symbol="") for _ in range(3)]
        contracts = _contracts()
        TqContractFetcher._mark_dominant_contracts(api, contracts)

        api.get_quote_list.assert_called_once_with(
            ["KQ.m@CFFEX.IC", "KQ.m@CFFEX.T", "KQ.m@SHFE.rb"]
        )

    def test_empty_underlying_leaves_false(self):
        """underlying_symbol 为空的品种不标记"""
        api = MagicMock()
        api.get_quote_list.return_value = [MagicMock(underlying_symbol="")]
        contracts = _contracts()
        TqContractFetcher._mark_dominant_contracts(api, contracts)

        assert all(c["is_main"] is False for c in contracts)

    def test_total_failure_leaves_all_false(self):
        """整体异常时所有合约 is_main=False（不阻塞主流程）"""
        api = MagicMock()
        api.get_quote_list.side_effect = RuntimeError("fatal")
        contracts = _contracts()
        TqContractFetcher._mark_dominant_contracts(api, contracts)

        assert all(c["is_main"] is False for c in contracts)


class TestFetchMarginMap:
    def _quote(self, instrument_id: str, margin):
        q = MagicMock()
        q.instrument_id = instrument_id
        q.margin = margin
        # quote.get("margin") 模拟 Entity 行为：NaN 判空，其余返回原值
        q.get.side_effect = lambda key, default=None: float("nan") if margin != margin else margin
        return q

    def test_returns_ready_margins(self):
        """全部就绪后返回 {instrument_id: margin}"""
        api = MagicMock()
        api.get_quote_list.return_value = [
            self._quote("SHFE.rb2501", 4356.0),
            self._quote("CFFEX.IC2611", 158601.6),
        ]

        result = TqContractFetcher._fetch_margin_map(api, ["SHFE.rb2501", "CFFEX.IC2611"])

        assert result == {"SHFE.rb2501": 4356.0, "CFFEX.IC2611": 158601.6}
        api.wait_update.assert_called()

    def test_timeout_keeps_partial(self):
        """超时后只保留已就绪部分（NaN 剔除）"""
        api = MagicMock()
        api.get_quote_list.return_value = [
            self._quote("SHFE.rb2501", 4356.0),
            self._quote("DCE.m2601", float("nan")),
        ]

        result = TqContractFetcher._fetch_margin_map(api, ["SHFE.rb2501", "DCE.m2601"], timeout=0.0)

        assert result == {"SHFE.rb2501": 4356.0}

    def test_subscription_failure_returns_empty(self):
        """订阅异常返回空 dict，不向上抛出"""
        api = MagicMock()
        api.get_quote_list.side_effect = RuntimeError("boom")

        assert TqContractFetcher._fetch_margin_map(api, ["SHFE.rb2501"]) == {}
