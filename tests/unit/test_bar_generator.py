import pytest
from datetime import datetime

from src.models.object import TickData, BarData, Interval, Exchange
from src.utils.bar_generator import BarGenerator


@pytest.mark.unit
class TestBarGenerator:
    """K线生成器测试"""
    
    @pytest.fixture
    def bar_generator(self):
        """创建K线生成器实例"""
        return BarGenerator()
    
    def test_bar_generator_initialization(self, bar_generator):
        """测试K线生成器初始化"""
        assert len(bar_generator.bars) == 0
        assert len(bar_generator._current_bars) == 0
    
    def test_get_bar_start_time_minute(self, bar_generator):
        """测试计算1分钟bar开始时间"""
        dt = datetime(2024, 1, 1, 9, 30, 45)
        bar_start = bar_generator._get_bar_start_time(dt, Interval.MINUTE)
        
        assert bar_start == datetime(2024, 1, 1, 9, 30, 0)
    
    def test_get_bar_start_time_hour(self, bar_generator):
        """测试计算1小时bar开始时间"""
        dt = datetime(2024, 1, 1, 9, 30, 45)
        bar_start = bar_generator._get_bar_start_time(dt, Interval.HOUR)
        
        assert bar_start == datetime(2024, 1, 1, 9, 0, 0)
    
    def test_get_bar_start_time_daily(self, bar_generator):
        """测试计算日bar开始时间"""
        dt = datetime(2024, 1, 1, 9, 30, 45)
        bar_start = bar_generator._get_bar_start_time(dt, Interval.DAILY)
        
        assert bar_start == datetime(2024, 1, 1, 0, 0, 0)
    
    def test_get_bar_returns_none_when_no_bars(self, bar_generator):
        """测试没有bar时返回None"""
        bar = bar_generator.get_bar("SHFE.rb2505", Interval.MINUTE)
        assert bar is None
    
    def test_get_bars_returns_empty_when_no_bars(self, bar_generator):
        """测试没有bar时返回空列表"""
        bars = bar_generator.get_bars("SHFE.rb2505", Interval.MINUTE)
        assert bars == []
