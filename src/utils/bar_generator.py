"""
K线生成器
从tick数据合成多周期bar数据（1m/5m/15m/1h/d），缓存历史数据
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

from src.models.object import TickData, BarData, Interval, Exchange
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BarGenerator:
    """K线生成器"""

    def __init__(self):
        # 按合约和周期缓存bar数据
        self.bars: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(dict))
        # 按合约和周期缓存当前正在生成的bar
        self._current_bars: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))

    def update_tick(self, tick: TickData):
        """
        更新tick数据，生成1分钟bar

        Args:
            tick: tick数据
        """
        key = tick.std_symbol

        # 更新1分钟bar
        self._update_bar(tick, Interval.MINUTE)

        # 生成其他周期bar（基于已有的1分钟bar）
        self._generate_higher_bars(tick)

    def _update_bar(self, tick: TickData, interval: Interval):
        """
        更新指定周期的bar

        Args:
            tick: tick数据
            interval: K线周期
        """
        key = tick.std_symbol
        interval_key = interval.value

        # 检查是否需要新建bar
        if self._current_bars[key][interval_key] is None:
            self._current_bars[key][interval_key] = {
                'symbol': tick.symbol,
                'exchange': tick.exchange,
                'interval': interval,
                'datetime': self._get_bar_start_time(tick.datetime, interval),
                'open_price': tick.last_price,
                'high_price': tick.last_price,
                'low_price': tick.last_price,
                'close_price': tick.last_price,
                'volume': tick.volume or 0,
                'turnover': tick.turnover or 0,
                'open_interest': tick.open_interest or 0,
            }
        else:
            # 检查是否跨越bar周期
            current = self._current_bars[key][interval_key]
            bar_start = self._get_bar_start_time(tick.datetime, interval)

            if bar_start != current['datetime']:
                # 保存完成的bar
                self.bars[key][interval_key] = BarData(**current)
                logger.debug(f"生成新bar: {key} {interval_key} {current['datetime']}")

                # 创建新bar
                self._current_bars[key][interval_key] = {
                    'symbol': tick.symbol,
                    'exchange': tick.exchange,
                    'interval': interval,
                    'datetime': bar_start,
                    'open_price': tick.last_price,
                    'high_price': tick.last_price,
                    'low_price': tick.last_price,
                    'close_price': tick.last_price,
                    'volume': tick.volume or 0,
                    'turnover': tick.turnover or 0,
                    'open_interest': tick.open_interest or 0,
                }
            else:
                # 更新当前bar
                current['high_price'] = max(current['high_price'], tick.last_price)
                current['low_price'] = min(current['low_price'], tick.last_price)
                current['close_price'] = tick.last_price
                if tick.volume:
                    current['volume'] += tick.volume
                if tick.turnover:
                    current['turnover'] += tick.turnover
                current['open_interest'] = tick.open_interest or 0

    def _generate_higher_bars(self, tick: TickData):
        """
        基于已有的1分钟bar生成更高周期bar

        Args:
            tick: tick数据
        """
        key = tick.std_symbol

        # 获取1分钟bar列表
        minute_bars = self._get_minute_bars(key)

        # 生成5分钟bar
        self._generate_bar_from_minute_bars(minute_bars, Interval.MINUTE, 5, tick)

        # 生成15分钟bar
        self._generate_bar_from_minute_bars(minute_bars, Interval.MINUTE, 15, tick)

        # 生成1小时bar
        self._generate_bar_from_minute_bars(minute_bars, Interval.MINUTE, 60, tick)

        # 生成日bar
        self._generate_bar_from_minute_bars(minute_bars, Interval.MINUTE, 1440, tick)

    def _generate_bar_from_minute_bars(self, minute_bars: List[BarData],
                                       base_interval: Interval, multiplier: int,
                                       tick: TickData):
        """
        从1分钟bar生成更高周期bar

        Args:
            minute_bars: 1分钟bar列表
            base_interval: 基础周期
            multiplier: 倍数（5=5分钟，60=1小时，1440=1天）
            tick: 当前tick
        """
        key = tick.std_symbol
        interval = Interval(f"{multiplier}m") if multiplier < 60 else (
            Interval.HOUR if multiplier == 60 else Interval.DAILY
        )
        interval_key = interval.value

        # 获取属于当前周期的1分钟bar
        bar_start = self._get_bar_start_time(tick.datetime, interval)
        period_minutes = multiplier

        # 筛选属于当前周期的bar
        period_bars = [
            b for b in minute_bars
            if b.datetime >= bar_start and
               b.datetime < bar_start + timedelta(minutes=period_minutes)
        ]

        if not period_bars:
            return

        # 聚合OHLCV
        current = {
            'symbol': tick.symbol,
            'exchange': tick.exchange,
            'interval': interval,
            'datetime': bar_start,
            'open_price': period_bars[0].open_price,
            'high_price': max(b.high_price for b in period_bars),
            'low_price': min(b.low_price for b in period_bars),
            'close_price': period_bars[-1].close_price,
            'volume': sum(b.volume for b in period_bars if b.volume),
            'turnover': sum(b.turnover for b in period_bars if b.turnover),
            'open_interest': period_bars[-1].open_interest,
        }

        # 更新或创建bar
        if self._current_bars[key][interval_key] is None:
            self._current_bars[key][interval_key] = current
        else:
            prev_start = self._current_bars[key][interval_key]['datetime']
            if bar_start != prev_start:
                # 保存完成的bar
                self.bars[key][interval_key] = BarData(**self._current_bars[key][interval_key])
                self._current_bars[key][interval_key] = current
            else:
                # 更新当前bar
                self._current_bars[key][interval_key] = current

    def _get_minute_bars(self, symbol: str) -> List[BarData]:
        """获取1分钟bar缓存"""
        interval_key = Interval.MINUTE.value
        if symbol in self.bars and interval_key in self.bars[symbol]:
            bar_data = self.bars[symbol][interval_key]
            if isinstance(bar_data, dict):
                return [BarData(**v) for v in bar_data.values()]
            elif isinstance(bar_data, BarData):
                return [bar_data]
        return []

    def _get_bar_start_time(self, dt: datetime, interval: Interval) -> datetime:
        """
        根据周期计算bar的开始时间

        Args:
            dt: 当前时间
            interval: K线周期

        Returns:
            bar的开始时间
        """
        if interval == Interval.MINUTE:
            # 1分钟：去除秒数
            return dt.replace(second=0, microsecond=0)
        elif interval == Interval.HOUR:
            # 1小时：整点
            return dt.replace(minute=0, second=0, microsecond=0)
        elif interval == Interval.DAILY:
            # 1天：零点
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            # 其他周期（5分钟、15分钟）
            minutes = int(interval.value.replace('m', ''))
            total_minutes = dt.hour * 60 + dt.minute
            period_minutes = (total_minutes // minutes) * minutes
            return dt.replace(hour=period_minutes // 60,
                           minute=period_minutes % 60,
                           second=0, microsecond=0)

    def get_bar(self, symbol: str, interval: Interval, n: int = 1) -> Optional[BarData]:
        """
        获取最新的N根bar

        Args:
            symbol: 合约代码
            interval: K线周期
            n: 获取根数

        Returns:
            最新bar或None
        """
        key = symbol
        interval_key = interval.value

        if key not in self.bars or interval_key not in self.bars[key]:
            return None

        bars = self.bars[key][interval_key]
        bar_list: List[BarData] = []
        if isinstance(bars, dict):
            bar_list = [BarData(**v) for v in bars.values()] if isinstance(next(iter(bars.values()), {}), dict) else [BarData(**bars)]
        elif isinstance(bars, BarData):
            bar_list = [bars]
        elif isinstance(bars, list):
            bar_list = bars

        if len(bar_list) >= n:
            return sorted(bar_list, key=lambda b: b.datetime)[-n]
        return None

    def get_bars(self, symbol: str, interval: Interval, count: int = 100) -> List[BarData]:
        """
        获取最新N根bar列表

        Args:
            symbol: 合约代码
            interval: K线周期
            count: 获取根数

        Returns:
            bar列表（按时间排序）
        """
        key = symbol
        interval_key = interval.value

        if key not in self.bars or interval_key not in self.bars[key]:
            return []

        bars = self.bars[key][interval_key]
        bar_list: List[BarData] = []
        if isinstance(bars, dict):
            bar_list = [BarData(**v) for v in bars.values()] if isinstance(next(iter(bars.values()), {}), dict) else [BarData(**bars)]
        elif isinstance(bars, BarData):
            bar_list = [bars]
        elif isinstance(bars, list):
            bar_list = bars

        return sorted(bar_list, key=lambda b: b.datetime)[-count:]


# 全局K线生成器实例
bar_generator = BarGenerator()
