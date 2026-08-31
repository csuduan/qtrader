"""
Trader JobManager 单元测试

覆盖：
- 遗留持仓平仓任务
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.trader.job_mgr import JobManager


def build_job_manager() -> JobManager:
    """构造不依赖配置的 JobManager"""
    mgr = JobManager.__new__(JobManager)
    mgr.config = MagicMock()
    mgr.trading_engine = MagicMock()
    mgr.position_manager = MagicMock()
    mgr.socket_server = None
    return mgr


@pytest.mark.asyncio
async def test_close_stale_positions_calls_enabled_strategies():
    """任务应调用所有启用策略的 close_stale_positions，禁用策略跳过"""
    mgr = build_job_manager()

    strategy_a = MagicMock()
    strategy_a.enabled = True
    strategy_a.close_stale_positions = AsyncMock()
    strategy_b = MagicMock()
    strategy_b.enabled = False
    strategy_b.close_stale_positions = AsyncMock()

    strategy_manager = MagicMock()
    strategy_manager.strategies = {"a": strategy_a, "b": strategy_b}

    ctx = MagicMock()
    ctx.get_strategy_manager.return_value = strategy_manager

    with patch("qtrader.trader.job_mgr.get_app_context", return_value=ctx):
        await mgr.close_stale_positions()

    strategy_a.close_stale_positions.assert_awaited_once()
    strategy_b.close_stale_positions.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_stale_positions_without_strategy_manager():
    """策略管理器未初始化时任务直接跳过，不抛异常"""
    mgr = build_job_manager()

    ctx = MagicMock()
    ctx.get_strategy_manager.return_value = None

    with patch("qtrader.trader.job_mgr.get_app_context", return_value=ctx):
        await mgr.close_stale_positions()
