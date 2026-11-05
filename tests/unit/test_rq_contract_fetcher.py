"""
RqContractFetcher 单元测试

mock rqdatac 模块，验证交易参数解析：
- 最小开仓手数多行取最后有效值、NaN 兜底 1
- 保证金率多头优先、缺失回退空头
- 郑商所长/短格式双 key 兼容 TqSdk
"""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from qtrader.manager.rq_contract_fetcher import RqContractFetcher

pytestmark = [pytest.mark.unit]

TODAY = pd.Timestamp("2026-11-05")


def _mock_rqdatac(order_book_ids: list[str], exchanges: dict[str, str]):
    """构造 mock rqdatac 模块（all_instruments + get_trading_parameters）"""
    futures = pd.DataFrame(
        {
            "order_book_id": order_book_ids,
            "exchange": [exchanges[ob] for ob in order_book_ids],
            "de_listed_date": ["2099-12-31"] * len(order_book_ids),
        }
    )

    def get_trading_parameters(order_book_ids=None, market="cn"):
        del market
        # multi-index DataFrame：level0=order_book_id，level1=trading_date
        idx = pd.MultiIndex.from_product(
            [order_book_ids, [TODAY]], names=["order_book_id", "trading_date"]
        )
        params = pd.DataFrame(index=idx)
        params["min_order_quantity"] = 1.0
        params["long_margin_ratio"] = 0.12
        params["short_margin_ratio"] = 0.12
        return params

    mod = MagicMock()
    mod.all_instruments.return_value = futures
    mod.futures.get_trading_parameters.side_effect = get_trading_parameters
    return mod


@pytest.fixture
def fetcher():
    return RqContractFetcher("user", "pass")


def _run_with_mock(fetcher, mod):
    with patch.dict(sys.modules, {"rqdatac": mod}):
        return fetcher.fetch_trading_parameters()


class TestFetchTradingParameters:
    def test_basic_fields(self, fetcher):
        """基础字段：手数与保证金率"""
        mod = _mock_rqdatac(["RB2505", "IF2611"], {"RB2505": "SHFE", "IF2611": "CFFEX"})
        result = _run_with_mock(fetcher, mod)

        assert result["RB2505"] == {"min_order_quantity": 1, "margin_rate": 0.12}
        assert result["IF2611"]["margin_rate"] == 0.12

    def test_czce_dual_keys(self, fetcher):
        """郑商所合约同时返回长格式(CF2501)与短格式(CF501)两种 key"""
        mod = _mock_rqdatac(["CF2501"], {"CF2501": "CZCE"})
        result = _run_with_mock(fetcher, mod)

        assert result["CF2501"]["margin_rate"] == 0.12
        assert result["CF501"] == result["CF2501"]

    def test_non_czce_no_short_key(self, fetcher):
        """非郑商所合约不生成短格式 key"""
        mod = _mock_rqdatac(["RB2505"], {"RB2505": "SHFE"})
        result = _run_with_mock(fetcher, mod)

        assert "RB2505" in result
        assert "R505" not in result

    def test_margin_long_missing_falls_back_short(self, fetcher):
        """多头保证金率缺失时回退空头"""
        mod = _mock_rqdatac(["RB2505"], {"RB2505": "SHFE"})

        original = mod.futures.get_trading_parameters.side_effect

        def patched(order_book_ids=None, market="cn"):
            df = original(order_book_ids=order_book_ids, market=market)
            df["long_margin_ratio"] = np.nan
            df["short_margin_ratio"] = 0.15
            return df

        mod.futures.get_trading_parameters.side_effect = patched
        result = _run_with_mock(fetcher, mod)

        assert result["RB2505"]["margin_rate"] == 0.15

    def test_min_order_multi_rows_takes_latest(self, fetcher):
        """手数多行时取最后一个有效值；全 NaN 兜底 1"""
        mod = _mock_rqdatac(["RB2505"], {"RB2505": "SHFE"})

        original = mod.futures.get_trading_parameters.side_effect

        def patched(order_book_ids=None, market="cn"):
            df = original(order_book_ids=order_book_ids, market=market)
            idx = pd.MultiIndex.from_tuples(
                [("RB2505", pd.Timestamp("2026-11-04")), ("RB2505", TODAY)],
                names=["order_book_id", "trading_date"],
            )
            df = df.reindex(idx)
            df["min_order_quantity"] = [np.nan, 4.0]
            df["long_margin_ratio"] = 0.12
            df["short_margin_ratio"] = 0.12
            return df

        mod.futures.get_trading_parameters.side_effect = patched
        result = _run_with_mock(fetcher, mod)

        assert result["RB2505"]["min_order_quantity"] == 4


class TestCzceToShort:
    def test_long_to_short(self):
        assert RqContractFetcher._czce_to_short("CF1701") == "CF701"
        assert RqContractFetcher._czce_to_short("TA2501") == "TA501"

    def test_non_matching_unchanged(self):
        """非"字母+4位数字"格式（如期权合约）原样返回"""
        assert RqContractFetcher._czce_to_short("IO2601-C-4000") == "IO2601-C-4000"
