"""
辅助函数模块
"""

from datetime import datetime, time

from src.utils.logger import get_logger

logger = get_logger(__name__)


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





def _get_float_param(config: dict, keys: list, default: float) -> float:
    """获取浮点数参数（支持多个key）"""
    for key in keys:
        val = config.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return default


def _get_str_param(config: dict, keys: list, default: str) -> str:
    """获取字符串参数（支持多个key）"""
    for key in keys:
        val = config.get(key)
        if val is not None:
            return str(val)
    return default


def _get_bool_param(config: dict, keys: list, default: bool) -> bool:
    """获取布尔参数（支持多个key）"""
    for key in keys:
        val = config.get(key)
        if val is not None:
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes")
            try:
                return bool(int(val))
            except (ValueError, TypeError):
                continue
    return default


def _get_int_param(config: dict, keys: list, default: int) -> int:
    """获取整数参数（支持多个key）"""
    for key in keys:
        val = config.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    return default


def _parse_time(time_str: str) -> time:
    """解析时间字符串"""
    try:
        h, m, s = time_str.split(":")
        return time(int(h), int(m), int(s))
    except Exception as e:
        logger.warning(f"时间解析失败: {time_str}, {e}")
        return time(0, 0, 0)

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
