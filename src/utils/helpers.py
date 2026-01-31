"""
辅助函数模块
"""

from datetime import datetime


def nanos_to_datetime_str(nanos: int) -> str:
    """
    将纳秒时间戳转换为datetime字符串

    Args:
        nanos: 纳秒时间戳（自1970-01-01 00:00:00 GMT）

    Returns:
        格式化的日期时间字符串
    """
    seconds = nanos / 1_000_000_000
    dt = datetime.fromtimestamp(seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def nanos_to_datetime(nanos: int) -> datetime:
    """
    将纳秒时间戳转换为datetime对象

    Args:
        nanos: 纳秒时间戳（自1970-01-01 00:00:00 GMT）

    Returns:
        datetime对象
    """
    seconds = nanos / 1_000_000_000
    return datetime.fromtimestamp(seconds)


def datetime_to_nanos(dt: datetime) -> int:
    """
    将datetime对象转换为纳秒时间戳

    Args:
        dt: datetime对象

    Returns:
        纳秒时间戳
    """
    return int(dt.timestamp() * 1_000_000_000)


def parse_symbol(symbol: str) -> tuple[str, str]:
    """
    解析合约代码

    Args:
        symbol: 完整合约代码，如 "SHFE.rb2505"

    Returns:
        (exchange_id, instrument_id) 元组
    """
    parts = symbol.split(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", symbol
