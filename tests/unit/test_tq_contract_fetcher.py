"""TqContractFetcher._mark_dominant_contracts 主力打标逻辑测试"""

from unittest.mock import MagicMock

import pytest

from qtrader.manager.tq_contract_fetcher import TqContractFetcher

pytestmark = [pytest.mark.unit]


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
