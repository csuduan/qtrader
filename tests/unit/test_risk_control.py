import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.utils.config_loader import RiskControlConfig
from src.trader.core.risk_control import RiskControl


@pytest.mark.unit
class TestRiskControl:
    """风控模块测试"""
    
    @pytest.fixture
    def risk_config(self):
        """创建风控配置"""
        return RiskControlConfig(
            max_daily_orders=100,
            max_daily_cancels=50,
            max_order_volume=10,
            max_split_volume=5,
            order_timeout=60
        )
    
    @pytest.fixture
    def risk_control(self, risk_config):
        """创建风控实例"""
        return RiskControl(risk_config)
    
    def test_risk_control_initialization(self, risk_control, risk_config):
        """测试风控模块初始化"""
        assert risk_control.config == risk_config
        assert risk_control.daily_order_count == 0
        assert risk_control.daily_cancel_count == 0
        assert risk_control._last_reset_date is None
    
    def test_check_order_success(self, risk_control):
        """测试订单风控检查通过"""
        result = risk_control.check_order(volume=5)
        assert result is True
    
    def test_check_order_volume_exceeds(self, risk_control):
        """测试订单风控拒绝：手数超限"""
        result = risk_control.check_order(volume=15)
        assert result is False
    
    def test_check_order_max_daily_reached(self, risk_control):
        """测试订单风控拒绝：达到单日最大次数"""
        risk_control.daily_order_count = 100
        risk_control._last_reset_date = datetime.now()
        result = risk_control.check_order(volume=5)
        assert result is False
    
    def test_check_cancel_success(self, risk_control):
        """测试撤单风控检查通过"""
        result = risk_control.check_cancel()
        assert result is True
    
    def test_check_cancel_max_daily_reached(self, risk_control):
        """测试撤单风控拒绝：达到单日最大次数"""
        risk_control.daily_cancel_count = 50
        risk_control._last_reset_date = datetime.now()
        result = risk_control.check_cancel()
        assert result is False
    
    def test_on_order_inserted(self, risk_control):
        """测试报单计数更新"""
        initial_count = risk_control.daily_order_count
        risk_control.on_order_inserted()
        assert risk_control.daily_order_count == initial_count + 1
    
    def test_on_order_cancelled(self, risk_control):
        """测试撤单计数更新"""
        initial_count = risk_control.daily_cancel_count
        risk_control.on_order_cancelled()
        assert risk_control.daily_cancel_count == initial_count + 1
    
    def test_get_status(self, risk_control, risk_config):
        """测试获取风控状态"""
        risk_control.daily_order_count = 10
        risk_control.daily_cancel_count = 5
        risk_control._last_reset_date = datetime.now()
        
        status = risk_control.get_status()
        
        assert status["daily_order_count"] == 10
        assert status["daily_cancel_count"] == 5
        assert status["max_daily_orders"] == risk_config.max_daily_orders
        assert status["max_daily_cancels"] == risk_config.max_daily_cancels
        assert status["max_order_volume"] == risk_config.max_order_volume
        assert status["remaining_orders"] == risk_config.max_daily_orders - 10
        assert status["remaining_cancels"] == risk_config.max_daily_cancels - 5
    
    @patch('src.trader.core.risk_control.datetime')
    def test_reset_on_new_day(self, mock_datetime, risk_control):
        """测试新的一天自动重置计数器"""
        today = datetime(2024, 1, 1)
        tomorrow = datetime(2024, 1, 2)
        
        # 设置当前时间为今天
        mock_datetime.now.return_value = today
        
        # 设置一些计数
        risk_control.daily_order_count = 50
        risk_control.daily_cancel_count = 25
        risk_control._last_reset_date = today
        
        # 模拟新的一天
        mock_datetime.now.return_value = tomorrow
        
        # 触发检查（应该触发重置）
        risk_control.check_order(volume=5)
        
        # 验证计数器已重置
        assert risk_control.daily_order_count == 0
        assert risk_control.daily_cancel_count == 0
        assert risk_control._last_reset_date == tomorrow
    
    def test_no_reset_on_same_day(self, risk_control):
        """测试同一天不重置计数器"""
        today = datetime.now()
        
        risk_control.daily_order_count = 10
        risk_control.daily_cancel_count = 5
        risk_control._last_reset_date = today
        
        # 触发检查（不应重置）
        risk_control.check_order(volume=5)
        
        # 验证计数器未重置
        assert risk_control.daily_order_count == 10
        assert risk_control.daily_cancel_count == 5
    
    def test_first_check_initializes_reset_date(self, risk_control):
        """测试首次检查初始化重置日期"""
        assert risk_control._last_reset_date is None
        
        risk_control.check_order(volume=5)
        
        assert risk_control._last_reset_date is not None
    
    @patch('src.trader.core.risk_control.logger')
    def test_order_rejection_logged(self, mock_logger, risk_control):
        """测试订单拒绝日志"""
        risk_control.daily_order_count = 100
        risk_control._last_reset_date = datetime.now()
        risk_control.check_order(volume=5)
        
        mock_logger.warning.assert_called()
    
    @patch('src.trader.core.risk_control.logger')
    def test_cancel_rejection_logged(self, mock_logger, risk_control):
        """测试撤单拒绝日志"""
        risk_control.daily_cancel_count = 50
        risk_control._last_reset_date = datetime.now()
        risk_control.check_cancel()
        
        mock_logger.warning.assert_called()
    
    @patch('src.trader.core.risk_control.logger')
    def test_new_day_reset_logged(self, mock_logger, risk_control):
        """测试新的一天重置日志"""
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        
        risk_control._last_reset_date = today
        
        with patch('src.trader.core.risk_control.datetime') as mock_datetime:
            mock_datetime.now.return_value = tomorrow
            risk_control.check_order(volume=5)
        
        mock_logger.info.assert_called()
    
    def test_multiple_order_checks(self, risk_control):
        """测试多次订单检查"""
        for i in range(5):
            result = risk_control.check_order(volume=i + 1)
            assert result is True
            risk_control.on_order_inserted()
        
        assert risk_control.daily_order_count == 5
    
    def test_multiple_cancel_checks(self, risk_control):
        """测试多次撤单检查"""
        for _ in range(3):
            result = risk_control.check_cancel()
            assert result is True
            risk_control.on_order_cancelled()
        
        assert risk_control.daily_cancel_count == 3
    
    def test_edge_case_zero_volume(self, risk_control):
        """测试边界情况：零手数"""
        result = risk_control.check_order(volume=0)
        assert result is True
    
    def test_edge_case_max_volume(self, risk_control):
        """测试边界情况：最大允许手数"""
        result = risk_control.check_order(volume=10)
        assert result is True
    
    def test_edge_case_max_volume_plus_one(self, risk_control):
        """测试边界情况：最大允许手数+1"""
        result = risk_control.check_order(volume=11)
        assert result is False
    
    def test_get_status_remaining_values(self, risk_control):
        """测试状态中的剩余值计算"""
        risk_control.daily_order_count = 25
        risk_control.daily_cancel_count = 10
        risk_control._last_reset_date = datetime.now()
        
        status = risk_control.get_status()
        
        assert status["remaining_orders"] == 75  # 100 - 25
        assert status["remaining_cancels"] == 40  # 50 - 10
