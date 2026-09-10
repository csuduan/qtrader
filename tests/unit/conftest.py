"""单元测试通用 fixture"""

import pytest


@pytest.fixture(autouse=True)
def _always_trading_session(monkeypatch):
    """放开交易时段守卫，保证单测不依赖墙钟时间

    生产代码在 OrderCmd.trig / TradingEngine.insert_order 中按当前时间判断
    盘中非交易时段；单测默认视为交易时段，需要验证时段拦截行为的用例
    自行 monkeypatch qtrader.trader.order_cmd / trading_engine 中的绑定。
    """
    monkeypatch.setattr(
        "qtrader.trader.order_cmd.is_symbol_trading_time",
        lambda symbol, now=None: True,
    )
    monkeypatch.setattr(
        "qtrader.trader.trading_engine.is_symbol_trading_time",
        lambda symbol, now=None: True,
    )
