"""
K线生成器
从tick数据合成多周期bar数据（M1/M5/M15/D1），支持回调通知
"""

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Callable

from qtrader.models.object import BarData, Exchange, Interval, TickData
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 周期映射: 配置字符串 -> (Interval, 分钟数)
INTERVAL_MAP = {
    "M1": (Interval.MINUTE, 1),
    "M5": (Interval.MINUTE_5, 5),
    "M15": (Interval.MINUTE_15, 15),
    "M30": (Interval.MINUTE_30, 30),
    "H1": (Interval.HOUR, 60),
    "D1": (Interval.DAILY, 1440),
}


def parse_interval(interval_str: str) -> tuple | None:
    """
    解析周期字符串

    Args:
        interval_str: 周期字符串，如 "M1", "M5", "M15", "D1"

    Returns:
        (Interval, 分钟数) 或 None
    """
    return INTERVAL_MAP.get(interval_str.upper())


class BarGenerator:
    """K线生成器 - 支持多周期和回调通知"""

    def __init__(self, symbol: str):
        """
        初始化BarGenerator

        Args:
            symbol: 合约代码
        """
        self.symbol = symbol
        self.std_symbol = f"{symbol}"

        # 已完成bar缓存容量（保留最近N根，满足指标计算与查询即可）
        self._max_completed_bars = 500

        # 当前正在生成的bar (key: interval_value)
        self._current_bars: dict[str, dict[str, Any]] = {}

        # 已完成的bar缓存 (key: interval_value -> deque of BarData)，限制容量保留最近N根
        self._completed_bars: dict[str, deque[BarData]] = defaultdict(
            lambda: deque(maxlen=self._max_completed_bars)
        )

        # 订阅的周期 (interval_value -> minutes)
        self._subscribed_intervals: dict[str, int] = {}

        # 回调函数列表 (interval_value -> list of callbacks)
        self._callbacks: dict[str, list[Callable[[BarData], None]]] = defaultdict(list)

        # 上一tick的当日累计成交量/成交额（用于计算增量，首个tick增量为0）
        self._last_tick_volume: float | None = None
        self._last_tick_turnover: float | None = None

        logger.debug(f"BarGenerator创建: {self.std_symbol}")

    def subscribe(
        self, interval_str: str, callback: (Callable[[BarData], None]) | None = None
    ) -> bool:
        """
        订阅指定周期的bar

        Args:
            interval_str: 周期字符串，如 "M1", "M5", "M15", "D1"
            callback: bar生成完成时的回调函数

        Returns:
            是否订阅成功
        """
        parsed = parse_interval(interval_str)
        if not parsed:
            logger.warning(f"不支持的周期: {interval_str}")
            return False

        interval, minutes = parsed
        interval_value = interval.value

        self._subscribed_intervals[interval_value] = minutes

        if callback:
            self._callbacks[interval_value].append(callback)

        logger.debug(f"订阅bar: {self.std_symbol} {interval_str}")
        return True

    def update_tick(self, tick: TickData) -> list[BarData]:
        """
        更新tick数据，生成bar

        Args:
            tick: tick数据

        Returns:
            本次更新中完成的BarData列表
        """
        completed_bars: list[BarData] = []

        # tick.volume/turnover 为当日累计值，先换算为本tick增量（所有周期共用）
        delta_volume, delta_turnover = self._calc_increment(tick)

        # 更新所有订阅的周期
        for interval_value, minutes in list(self._subscribed_intervals.items()):
            bar = self._update_bar(tick, interval_value, minutes, delta_volume, delta_turnover)
            if bar:
                completed_bars.append(bar)

        return completed_bars

    def _calc_increment(self, tick: TickData) -> tuple[float, float]:
        """
        计算tick相对上一tick的增量成交量/成交额

        tick.volume 为当日累计值；累计值回绕（跨交易日重置或乱序）时按全量计；
        首个tick增量为0（无基准线）。

        Args:
            tick: tick数据

        Returns:
            (增量成交量, 增量成交额)
        """
        volume = tick.volume or 0
        turnover = tick.turnover or 0

        if self._last_tick_volume is None or self._last_tick_turnover is None:
            delta_volume, delta_turnover = 0.0, 0.0
        else:
            delta_volume = volume - self._last_tick_volume
            delta_turnover = turnover - self._last_tick_turnover
            if delta_volume < 0 or delta_turnover < 0:
                # 累计值回绕（新交易日），按全量计
                delta_volume, delta_turnover = volume, turnover

        self._last_tick_volume = volume
        self._last_tick_turnover = turnover
        return delta_volume, delta_turnover

    def _update_bar(
        self,
        tick: TickData,
        interval_value: str,
        minutes: int,
        delta_volume: float,
        delta_turnover: float,
    ) -> BarData | None:
        """
        更新指定周期的bar

        Args:
            tick: tick数据
            interval_value: 周期值
            minutes: 分钟数

        Returns:
            如果bar完成则返回BarData，否则返回None
        """
        current_bar = self._current_bars.get(interval_value)
        bar_start = self._get_bar_start_time(tick, minutes)

        if current_bar is None:
            # 创建新bar
            self._current_bars[interval_value] = {
                "symbol": self.symbol,
                "interval": self._get_interval_enum(minutes),
                "datetime": bar_start,
                "open_price": tick.last_price,
                "high_price": tick.last_price,
                "low_price": tick.last_price,
                "close_price": tick.last_price,
                "volume": delta_volume,
                "turnover": delta_turnover,
                "open_interest": tick.open_interest or 0,
            }
            return None

        # 检查是否跨越bar周期
        if bar_start != current_bar["datetime"]:
            # bar完成，创建BarData
            completed_bar = BarData(**current_bar)
            self._completed_bars[interval_value].append(completed_bar)

            # 触发回调
            self._notify_bar_completed(interval_value, completed_bar)

            # 创建新bar
            self._current_bars[interval_value] = {
                "symbol": self.symbol,
                "interval": self._get_interval_enum(minutes),
                "datetime": bar_start,
                "open_price": tick.last_price,
                "high_price": tick.last_price,
                "low_price": tick.last_price,
                "close_price": tick.last_price,
                "volume": delta_volume,
                "turnover": delta_turnover,
                "open_interest": tick.open_interest or 0,
            }

            return completed_bar
        else:
            # 更新当前bar
            current_bar["high_price"] = max(current_bar["high_price"], tick.last_price)
            current_bar["low_price"] = min(current_bar["low_price"], tick.last_price)
            current_bar["close_price"] = tick.last_price
            current_bar["volume"] += delta_volume
            current_bar["turnover"] += delta_turnover
            current_bar["open_interest"] = tick.open_interest or 0
            current_bar["update_time"] = tick.datetime

        return None

    def _notify_bar_completed(self, interval_value: str, bar: BarData):
        """
        通知bar完成

        Args:
            interval_value: 周期值
            bar: 完成的bar数据
        """
        callbacks = self._callbacks.get(interval_value, [])
        for callback in callbacks:
            try:
                callback(bar)
            except Exception as e:
                logger.exception(f"Bar回调执行失败: {e}")

    def _get_bar_start_time(self, tick: TickData, minutes: int) -> datetime:
        """
        计算bar的开始时间

        日线及以上：优先按 tick.trading_day 切分（夜盘归属下一交易日，
        避免同一交易日被切成两根日线）；无交易日信息时退化为自然日。

        Args:
            tick: tick数据
            minutes: bar周期（分钟）

        Returns:
            bar开始时间
        """
        dt = tick.datetime
        if minutes >= 1440:  # 日线及以上
            trading_day = (tick.trading_day or "").replace("-", "")
            if len(trading_day) == 8 and trading_day.isdigit():
                return datetime.strptime(trading_day, "%Y%m%d")
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        elif minutes >= 60:  # 小时线
            hour = (dt.hour // (minutes // 60)) * (minutes // 60)
            return dt.replace(hour=hour, minute=0, second=0, microsecond=0)
        else:  # 分钟线
            total_minutes = dt.hour * 60 + dt.minute
            period_minutes = (total_minutes // minutes) * minutes
            return dt.replace(
                hour=period_minutes // 60, minute=period_minutes % 60, second=0, microsecond=0
            )

    def _get_interval_enum(self, minutes: int) -> Interval:
        """
        根据分钟数获取Interval枚举

        Args:
            minutes: 分钟数

        Returns:
            Interval枚举值
        """
        if minutes == 1:
            return Interval.MINUTE
        elif minutes == 5:
            return Interval.MINUTE_5
        elif minutes == 15:
            return Interval.MINUTE_15
        elif minutes == 30:
            return Interval.MINUTE_30
        elif minutes == 60:
            return Interval.HOUR
        else:
            return Interval.DAILY

    def get_bar(self, interval_str: str, n: int = 1) -> BarData | None:
        """
        获取最新的N根bar

        Args:
            interval_str: 周期字符串
            n: 获取根数

        Returns:
            最新bar或None
        """
        parsed = parse_interval(interval_str)
        if not parsed:
            return None

        interval, _ = parsed
        interval_value = interval.value

        bars: list[BarData] = list(self._completed_bars.get(interval_value, ()))
        if len(bars) >= n:
            return sorted(bars, key=lambda b: b.datetime)[-n]
        return None

    def get_bars(self, interval_str: str, count: int = 100) -> list[BarData]:
        """
        获取最新N根bar列表

        Args:
            interval_str: 周期字符串
            count: 获取根数

        Returns:
            bar列表（按时间排序）
        """
        parsed = parse_interval(interval_str)
        if not parsed:
            return []

        interval, _ = parsed
        interval_value = interval.value

        bars: list[BarData] = list(self._completed_bars.get(interval_value, ()))
        return sorted(bars, key=lambda b: b.datetime)[-count:]


class MultiSymbolBarGenerator:
    """多合约Bar生成器管理器"""

    def __init__(self):
        # 每个合约一个BarGenerator: {std_symbol -> BarGenerator}
        self._generators: dict[str, BarGenerator] = {}

    def get_or_create(self, symbol: str) -> BarGenerator:
        """
        获取或创建BarGenerator

        Args:
            symbol: 合约代码

        Returns:
            BarGenerator实例
        """
        std_symbol = f"{symbol}"

        if std_symbol not in self._generators:
            self._generators[std_symbol] = BarGenerator(symbol)
            logger.debug(f"创建BarGenerator: {std_symbol}")

        return self._generators[std_symbol]

    def get(self, symbol: str) -> BarGenerator | None:
        """
        获取BarGenerator

        Args:
            symbol: 合约代码

        Returns:
            BarGenerator实例或None
        """
        std_symbol = f"{symbol}"
        return self._generators.get(std_symbol)

    def update_tick(self, tick: TickData) -> dict[str, list[BarData]]:
        """
        更新tick数据到所有相关的BarGenerator

        Args:
            tick: tick数据

        Returns:
            {std_symbol -> [completed_bar, ...]}
        """
        results = {}

        for std_symbol, generator in self._generators.items():
            if tick.symbol == std_symbol:
                completed = generator.update_tick(tick)
                if completed:
                    results[std_symbol] = completed

        return results

    def remove(self, symbol: str) -> bool:
        """
        移除BarGenerator

        Args:
            symbol: 合约代码

        Returns:
            是否成功移除
        """
        std_symbol = f"{symbol}"
        if std_symbol in self._generators:
            del self._generators[std_symbol]
            logger.debug(f"移除BarGenerator: {std_symbol}")
            return True
        return False

    def clear(self) -> None:
        """清除所有BarGenerator"""
        self._generators.clear()
        logger.debug("清除所有BarGenerator")


# 全局多合约Bar生成器实例
multi_bar_generator = MultiSymbolBarGenerator()
