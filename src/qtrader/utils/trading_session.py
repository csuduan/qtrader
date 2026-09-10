"""
交易时段判断工具

按国内期货交易所划分日盘与夜盘时段，用于：
- 直接报单（TradingEngine.insert_order）在盘中非交易时段（小节休息/午休/闭市）拦截
- 报单指令（OrderCmd）空跑挂起：不报单、不撤单、不消耗报单次数、冻结总超时

说明：
- 时段为交易所级粒度；夜盘收尾按该所最晚品种取值（宁晚拦不早拦，误拦会让指令
  空转，漏拦由交易所拒单 + OrderCmd 重试兜底）。
- 不含节假日日历：法定节假日报单由交易所拒绝，OrderCmd 会重试，恢复后继续执行。
"""

from dataclasses import dataclass
from datetime import datetime, time

from qtrader.models.object import Exchange

__all__ = ["is_trading_time", "is_symbol_trading_time", "parse_exchange_from_symbol"]


@dataclass(frozen=True)
class ExchangeSession:
    """交易所交易时段

    Attributes:
        day: 日盘时段列表（起止均在当日内，不跨零点）
        night: 夜盘（开始时刻, 次日结束时刻），None 表示无夜盘；结束时刻小于开始时刻表示跨零点
    """

    day: tuple[tuple[time, time], ...]
    night: tuple[time, time] | None = None


# 商品期货共同日盘：上午两小节（10:15-10:30 休息）+ 下午（13:30-15:00）
_COMMODITY_DAY = (
    (time(9, 0), time(10, 15)),
    (time(10, 30), time(11, 30)),
    (time(13, 30), time(15, 0)),
)

SESSIONS: dict[Exchange, ExchangeSession] = {
    # 中金所：无小节休息、无夜盘
    Exchange.CFFEX: ExchangeSession(
        day=((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))),
    ),
    # 上期所/上能源：夜盘最晚品种收于次日 02:30
    Exchange.SHFE: ExchangeSession(day=_COMMODITY_DAY, night=(time(21, 0), time(2, 30))),
    Exchange.INE: ExchangeSession(day=_COMMODITY_DAY, night=(time(21, 0), time(2, 30))),
    # 大商所/郑商所：夜盘最晚品种收于次日 23:30 内（跨零点品种极少，按当日收尾处理）
    Exchange.DCE: ExchangeSession(day=_COMMODITY_DAY, night=(time(21, 0), time(23, 30))),
    Exchange.CZCE: ExchangeSession(day=_COMMODITY_DAY, night=(time(21, 0), time(23, 30))),
    # 广期所：无跨零点夜盘
    Exchange.GFEX: ExchangeSession(day=_COMMODITY_DAY, night=(time(21, 0), time(23, 0))),
}

# 交易所代码 → Exchange（用于合约代码前缀/后缀解析）
_EXCHANGE_CODES = {ex.value.upper(): ex for ex in SESSIONS}


def parse_exchange_from_symbol(symbol: str) -> Exchange | None:
    """
    从合约代码解析交易所

    支持格式："SHFE.rb2505"、"rb2505.SHFE"；裸合约代码（如 "rb2505"）无法解析返回 None。

    Args:
        symbol: 合约代码

    Returns:
        交易所枚举，无法识别时返回 None
    """
    parts = symbol.split(".")
    if len(parts) == 2:
        for part in parts:
            exchange = _EXCHANGE_CODES.get(part.upper())
            if exchange is not None:
                return exchange
    return None


def is_trading_time(exchange: Exchange, now: datetime | None = None) -> bool:
    """
    判断指定交易所当前是否处于交易时段

    周末规则：周日全天非交易；周六仅凌晨（周五夜盘延续）交易。
    未知交易所（不在 SESSIONS 中）返回 True，由交易所拒单兜底。

    Args:
        exchange: 交易所
        now: 判定时刻，默认当前时间

    Returns:
        是否在交易时段
    """
    session = SESSIONS.get(exchange)
    if session is None:
        return True

    now = now or datetime.now()
    weekday, t = now.weekday(), now.time()

    if session.night is not None:
        night_start, night_end = session.night
        # 当晚夜盘（周一至周五）：到达开始时刻即可（持续到当日收尾或午夜）
        if t >= night_start and weekday <= 4:
            return True
        # 次日凌晨夜盘延续（仅跨零点夜盘，如 21:00-02:30）：周二至周六凌晨，周日无
        if night_end < night_start and t <= night_end and 0 <= weekday <= 5:
            return True

    # 日盘（周一至周五）
    if weekday <= 4:
        for start, end in session.day:
            if start <= t <= end:
                return True
    return False


def is_symbol_trading_time(symbol: str, now: datetime | None = None) -> bool:
    """
    判断合约代码对应交易所当前是否处于交易时段

    无法解析交易所的裸合约代码返回 True（不拦截，由交易所拒单兜底）。

    Args:
        symbol: 合约代码（支持 "SHFE.rb2505" / "rb2505.SHFE" 格式）
        now: 判定时刻，默认当前时间

    Returns:
        是否在交易时段
    """
    exchange = parse_exchange_from_symbol(symbol)
    if exchange is None:
        return True
    return is_trading_time(exchange, now)
