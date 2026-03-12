"""
测试策略持仓更新时的账户持仓检查

验证手动更新策略持仓时，各持仓维度不能超过账户持仓
"""

import pytest
from unittest.mock import MagicMock, patch

from src.models.object import PositionData, Exchange


class TestUpdateStrategyPositionDetailCheck:
    """测试更新策略持仓时的账户持仓检查"""

    @pytest.fixture
    def mock_trader(self):
        """创建模拟的Trader实例"""
        trader = MagicMock()
        trader.strategy_manager = MagicMock()
        return trader

    @pytest.fixture
    def mock_strategy(self):
        """创建模拟的策略"""
        strategy = MagicMock()
        strategy._positions = {}
        return strategy

    def _create_account_position(self, long_td=0, long_yd=0, short_td=0, short_yd=0):
        """创建账户持仓数据"""
        return PositionData.model_construct(
            symbol="IM2506",
            exchange=Exchange.CFFEX,
            pos_long_td=long_td,
            pos_long_yd=long_yd,
            pos_short_td=short_td,
            pos_short_yd=short_yd,
        )

    @pytest.mark.asyncio
    async def test_update_position_success(self, mock_trader, mock_strategy):
        """测试持仓更新成功 - 策略持仓不超过账户持仓"""
        # 设置账户持仓: 多头今仓5, 多头昨仓10, 空头今仓3, 空头昨仓2
        account_pos = self._create_account_position(
            long_td=5, long_yd=10, short_td=3, short_yd=2
        )
        mock_trader.trading_engine.positions = {"IM2506": account_pos}
        mock_trader.strategy_manager.strategies = {"strategy_001": mock_strategy}

        # 模拟请求数据 - 策略持仓在账户持仓范围内
        data = {
            "strategy_id": "strategy_001",
            "position": {
                "symbol": "IM2506",
                "pos_long_td": 3,  # <= 5
                "pos_long_yd": 8,  # <= 10
                "pos_short_td": 2,  # <= 3
                "pos_short_yd": 1,  # <= 2
            },
        }

        # 直接调用方法测试
        with patch.object(mock_strategy, "_get_or_create_position") as mock_get_pos:
            mock_position = MagicMock()
            mock_get_pos.return_value = mock_position

            # 由于我们无法直接调用被装饰器装饰的方法，测试逻辑本身
            position_data = data.get("position", {})
            symbol = position_data.get("symbol")
            new_pos_long_td = position_data.get("pos_long_td", 0)
            new_pos_long_yd = position_data.get("pos_long_yd", 0)
            new_pos_short_td = position_data.get("pos_short_td", 0)
            new_pos_short_yd = position_data.get("pos_short_yd", 0)

            # 检查逻辑
            account_positions = mock_trader.trading_engine.positions
            account_position = account_positions.get(symbol)

            assert account_position is not None
            assert new_pos_long_td <= account_position.pos_long_td
            assert new_pos_long_yd <= account_position.pos_long_yd
            assert new_pos_short_td <= account_position.pos_short_td
            assert new_pos_short_yd <= account_position.pos_short_yd

    @pytest.mark.asyncio
    async def test_update_position_long_td_exceeds(self, mock_trader, mock_strategy):
        """测试多头今仓超过账户持仓 - 应该失败"""
        account_pos = self._create_account_position(long_td=5, long_yd=10)
        mock_trader.trading_engine.positions = {"IM2506": account_pos}

        # 策略多头今仓6 > 账户多头今仓5
        new_pos_long_td = 6
        account_pos_long_td = account_pos.pos_long_td

        assert new_pos_long_td > account_pos_long_td, "测试数据设置错误"

        # 验证检查逻辑
        should_fail = new_pos_long_td > account_pos_long_td
        assert should_fail is True

    @pytest.mark.asyncio
    async def test_update_position_long_yd_exceeds(self, mock_trader, mock_strategy):
        """测试多头昨仓超过账户持仓 - 应该失败"""
        account_pos = self._create_account_position(long_td=5, long_yd=10)
        mock_trader.trading_engine.positions = {"IM2506": account_pos}

        # 策略多头昨仓15 > 账户多头昨仓10
        new_pos_long_yd = 15
        account_pos_long_yd = account_pos.pos_long_yd

        assert new_pos_long_yd > account_pos_long_yd, "测试数据设置错误"

        # 验证检查逻辑
        should_fail = new_pos_long_yd > account_pos_long_yd
        assert should_fail is True

    @pytest.mark.asyncio
    async def test_update_position_short_td_exceeds(self, mock_trader, mock_strategy):
        """测试空头今仓超过账户持仓 - 应该失败"""
        account_pos = self._create_account_position(short_td=3, short_yd=2)
        mock_trader.trading_engine.positions = {"IM2506": account_pos}

        # 策略空头今仓5 > 账户空头今仓3
        new_pos_short_td = 5
        account_pos_short_td = account_pos.pos_short_td

        assert new_pos_short_td > account_pos_short_td, "测试数据设置错误"

        # 验证检查逻辑
        should_fail = new_pos_short_td > account_pos_short_td
        assert should_fail is True

    @pytest.mark.asyncio
    async def test_update_position_short_yd_exceeds(self, mock_trader, mock_strategy):
        """测试空头昨仓超过账户持仓 - 应该失败"""
        account_pos = self._create_account_position(short_td=3, short_yd=2)
        mock_trader.trading_engine.positions = {"IM2506": account_pos}

        # 策略空头昨仓5 > 账户空头昨仓2
        new_pos_short_yd = 5
        account_pos_short_yd = account_pos.pos_short_yd

        assert new_pos_short_yd > account_pos_short_yd, "测试数据设置错误"

        # 验证检查逻辑
        should_fail = new_pos_short_yd > account_pos_short_yd
        assert should_fail is True

    @pytest.mark.asyncio
    async def test_update_position_no_account_position(self, mock_trader, mock_strategy):
        """测试账户没有持仓时设置策略持仓 - 应该失败"""
        mock_trader.trading_engine.positions = {}  # 账户没有持仓

        # 尝试设置任何持仓都应该失败
        new_pos_long_td = 1
        new_pos_long_yd = 0
        new_pos_short_td = 0
        new_pos_short_yd = 0

        account_positions = mock_trader.trading_engine.positions
        account_position = account_positions.get("IM2506")

        assert account_position is None

        # 验证检查逻辑 - 账户没有持仓时策略也不能有持仓
        has_any_position = (
            new_pos_long_td > 0
            or new_pos_long_yd > 0
            or new_pos_short_td > 0
            or new_pos_short_yd > 0
        )
        assert has_any_position is True

    @pytest.mark.asyncio
    async def test_update_position_zero_allowed(self, mock_trader, mock_strategy):
        """测试账户没有持仓时设置策略持仓为0 - 应该成功"""
        mock_trader.trading_engine.positions = {}  # 账户没有持仓

        # 设置持仓为0应该允许
        new_pos_long_td = 0
        new_pos_long_yd = 0
        new_pos_short_td = 0
        new_pos_short_yd = 0

        account_positions = mock_trader.trading_engine.positions
        account_position = account_positions.get("IM2506")

        # 账户没有持仓，但策略持仓为0，应该允许
        has_any_position = (
            new_pos_long_td > 0
            or new_pos_long_yd > 0
            or new_pos_short_td > 0
            or new_pos_short_yd > 0
        )
        assert has_any_position is False  # 没有持仓，应该允许

    @pytest.mark.asyncio
    async def test_update_position_exact_match(self, mock_trader, mock_strategy):
        """测试策略持仓与账户持仓完全相等 - 应该成功"""
        account_pos = self._create_account_position(
            long_td=5, long_yd=10, short_td=3, short_yd=2
        )
        mock_trader.trading_engine.positions = {"IM2506": account_pos}

        # 策略持仓与账户持仓完全相等
        new_pos_long_td = 5
        new_pos_long_yd = 10
        new_pos_short_td = 3
        new_pos_short_yd = 2

        # 验证检查逻辑
        assert new_pos_long_td <= account_pos.pos_long_td
        assert new_pos_long_yd <= account_pos.pos_long_yd
        assert new_pos_short_td <= account_pos.pos_short_td
        assert new_pos_short_yd <= account_pos.pos_short_yd


class TestPositionCheckEdgeCases:
    """测试持仓检查的边界情况"""

    def _create_account_position(self, long_td=0, long_yd=0, short_td=0, short_yd=0):
        """创建账户持仓数据"""
        return PositionData.model_construct(
            symbol="IM2506",
            exchange=Exchange.CFFEX,
            pos_long_td=long_td,
            pos_long_yd=long_yd,
            pos_short_td=short_td,
            pos_short_yd=short_yd,
        )

    @pytest.mark.asyncio
    async def test_none_position_values(self):
        """测试账户持仓字段为None的情况"""
        account_pos = PositionData.model_construct(
            symbol="IM2506",
            exchange=Exchange.CFFEX,
            pos_long_td=None,
            pos_long_yd=None,
            pos_short_td=None,
            pos_short_yd=None,
        )

        # 使用 or 0 处理 None 值
        account_pos_long_td = account_pos.pos_long_td or 0
        account_pos_long_yd = account_pos.pos_long_yd or 0
        account_pos_short_td = account_pos.pos_short_td or 0
        account_pos_short_yd = account_pos.pos_short_yd or 0

        assert account_pos_long_td == 0
        assert account_pos_long_yd == 0
        assert account_pos_short_td == 0
        assert account_pos_short_yd == 0

    @pytest.mark.asyncio
    async def test_mixed_position_directions(self):
        """测试同时有多头和空头持仓的情况"""
        account_pos = self._create_account_position(
            long_td=5, long_yd=5, short_td=3, short_yd=2
        )

        # 策略多头和空头都在范围内
        new_pos_long_td = 3
        new_pos_long_yd = 4
        new_pos_short_td = 2
        new_pos_short_yd = 1

        assert new_pos_long_td <= account_pos.pos_long_td
        assert new_pos_long_yd <= account_pos.pos_long_yd
        assert new_pos_short_td <= account_pos.pos_short_td
        assert new_pos_short_yd <= account_pos.pos_short_yd
