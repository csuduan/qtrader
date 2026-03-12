import pytest
from datetime import datetime

from src.utils.helpers import (
    nanos_to_datetime_str,
    nanos_to_datetime,
    datetime_to_nanos,
    parse_symbol
)


@pytest.mark.unit
class TestHelpers:
    """辅助函数测试"""
    
    def test_nanos_to_datetime_str(self):
        """测试纳秒转datetime字符串"""
        nanos = 1704067200000000000  # 2024-01-01 00:00:00 (UTC)
        result = nanos_to_datetime_str(nanos)
        
        # 由于本地时区是UTC+8，所以会显示为08:00:00
        assert result == "2024-01-01 08:00:00"
    
    def test_nanos_to_datetime_str_with_time(self):
        """测试纳秒转datetime字符串（带时间）"""
        # 2024-01-01 10:00:00 UTC+8 = 2024-01-01 02:00:00 UTC
        nanos = 1704067200000000000 + (2 * 3600 * 1_000_000_000)
        result = nanos_to_datetime_str(nanos)
        
        assert result == "2024-01-01 10:00:00"
    
    def test_nanos_to_datetime(self):
        """测试纳秒转datetime对象"""
        nanos = 1704067200000000000  # 2024-01-01 00:00:00 (UTC)
        result = nanos_to_datetime(nanos)
        
        # 本地时区是UTC+8
        assert result == datetime(2024, 1, 1, 8, 0, 0)
    
    def test_nanos_to_datetime_with_fractional_seconds(self):
        """测试纳秒转datetime对象（带小数秒）"""
        nanos = 1704067200500000000  # 2024-01-01 00:00:00.5 (UTC)
        result = nanos_to_datetime(nanos)
        
        # 本地时区是UTC+8，纳秒精度会丢失（转为微秒）
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1
        assert result.hour == 8
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 500000
    
    def test_datetime_to_nanos(self):
        """测试datetime转纳秒"""
        dt = datetime(2024, 1, 1, 0, 0, 0)
        result = datetime_to_nanos(dt)
        
        # 本地时区是UTC+8，所以2024-01-01 00:00:00 (local) = 2023-12-31 16:00:00 (UTC)
        expected = 1704038400000000000
        assert result == expected
    
    def test_datetime_to_nanos_with_time(self):
        """测试datetime转纳秒（带时间）"""
        dt = datetime(2024, 1, 1, 10, 30, 45)
        result = datetime_to_nanos(dt)
        
        # 本地时区是UTC+8，所以减去8小时
        expected = 1704076245000000000
        assert result == expected
    
    def test_datetime_nanos_roundtrip(self):
        """测试datetime和纳秒相互转换的往返一致性"""
        original_dt = datetime(2024, 1, 1, 15, 30, 45)
        
        nanos = datetime_to_nanos(original_dt)
        result_dt = nanos_to_datetime(nanos)
        
        assert result_dt == original_dt
    
    def test_parse_symbol_with_exchange(self):
        """测试解析带交易所的合约代码"""
        symbol = "SHFE.rb2505"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "SHFE"
        assert instrument == "rb2505"
    
    def test_parse_symbol_without_exchange(self):
        """测试解析不带交易所的合约代码"""
        symbol = "rb2505"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == ""
        assert instrument == "rb2505"
    
    def test_parse_symbol_cffex(self):
        """测试解析中金所合约代码"""
        symbol = "CFFEX.IF2501"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "CFFEX"
        assert instrument == "IF2501"
    
    def test_parse_symbol_dce(self):
        """测试解析大商所合约代码"""
        symbol = "DCE.m2505"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "DCE"
        assert instrument == "m2505"
    
    def test_parse_symbol_czce(self):
        """测试解析郑商所合约代码"""
        symbol = "CZCE.SR405"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "CZCE"
        assert instrument == "SR405"
    
    def test_nanos_to_datetime_str_edge_case_epoch(self):
        """测试边界情况：Unix时间戳起点"""
        nanos = 0
        result = nanos_to_datetime_str(nanos)
        
        # 本地时区是UTC+8
        assert result == "1970-01-01 08:00:00"
    
    def test_nanos_to_datetime_str_edge_case_negative(self):
        """测试边界情况：负纳秒（Unix时间戳之前）"""
        nanos = -86400000000000  # 1969-12-31 00:00:00 (UTC)
        result = nanos_to_datetime_str(nanos)
        
        # 本地时区是UTC+8
        assert result == "1969-12-31 08:00:00"
    
    def test_datetime_to_nanos_epoch(self):
        """测试边界情况：Unix时间戳起点转纳秒"""
        dt = datetime(1970, 1, 1, 0, 0, 0)
        result = datetime_to_nanos(dt)
        
        # 本地时区是UTC+8，所以是Unix时间戳 -8小时
        assert result == -28800000000000
    
    def test_parse_symbol_empty_string(self):
        """测试边界情况：空字符串"""
        symbol = ""
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == ""
        assert instrument == ""
    
    def test_parse_symbol_multiple_dots(self):
        """测试边界情况：多个点"""
        symbol = "SHFE.rb.2505"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "SHFE"
        assert instrument == "rb.2505"
    
    def test_parse_symbol_leading_dot(self):
        """测试边界情况：前导点"""
        symbol = ".rb2505"
        exchange, instrument = parse_symbol(symbol)
        
        # split(".", 1)会返回 ['', 'rb2505']
        # 但实际代码中split(".")会返回 ['', '', 'rb2505']
        # 然后parts[0] = "", parts[1] = "rb2505"
        assert exchange == ""
        assert instrument == "rb2505"
    
    def test_parse_symbol_trailing_dot(self):
        """测试边界情况：尾随点"""
        symbol = "SHFE."
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "SHFE"
        assert instrument == ""
    
    def test_nanos_conversion_precision(self):
        """测试纳秒转换精度"""
        # 1纳秒的精度
        nanos = 1704067200000000001  # 2024-01-01 00:00:00.000000001
        
        # 转换为datetime会丢失纳秒精度（Python datetime只支持微秒）
        dt = nanos_to_datetime(nanos)
        back_nanos = datetime_to_nanos(dt)
        
        # 纳秒精度会丢失，但在微秒级别应该是准确的
        assert abs(nanos - back_nanos) < 1000
    
    def test_parse_symbol_case_sensitivity(self):
        """测试解析符号的大小写敏感性"""
        symbol = "shfe.rb2505"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "shfe"
        assert instrument == "rb2505"
    
    def test_parse_symbol_with_numbers(self):
        """测试解析包含数字的交易所代码"""
        symbol = "SFE123.rb2505"
        exchange, instrument = parse_symbol(symbol)
        
        assert exchange == "SFE123"
        assert instrument == "rb2505"
