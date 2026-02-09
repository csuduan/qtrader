"""
RSI 可执行策略
基于策略参考 strategy_rsi_demo.py 转换为可执行策略

策略逻辑：
1. 计算短周期和长周期K线的RSI
2. 根据RSI交叉信号产生交易信号
3. 在交易窗口内开仓
4. 设置止盈止损
5. 强制平仓时间平仓
"""

from collections import deque
from datetime import datetime, time,timedelta
from typing import Optional, List

import numpy as np
from pydantic import BaseModel, Field

from src.models.object import BarData, Direction, Offset, OrderData, PositionData
from src.trader.order_cmd import OrderCmd
from src.trader.strategy.base_strategy import BaseStrategy, BaseParam, Signal
from src.utils.config_loader import StrategyConfig
from src.utils.helpers import (
    _get_bool_param,
    _get_float_param,
    _get_int_param,
    _get_str_param,
    _parse_time,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 数值计算精度控制
EPS = 1e-12


class RsiParam(BaseParam):
    """RSI策略参数"""
    # RSI参数
    rsi_n: int = Field(default=5, title="RSI周期")  # RSI计算周期
    short_k: int = Field(default=5, title="短周期")  # 短K线周期（分钟）
    long_k: int = Field(default=15, title="长周期")  # 长K线周期（分钟）
    # RSI阈值
    long_threshold: float = Field(default=50.0, title="长RSI阈值")  # 长RSI多头阈值 (对应原L)
    short_threshold: float = Field(default=55.0, title="短RSI阈值")  # 短RSI多头阈值 (对应原S)
    # 交易时间窗口（使用time类型以便时间比较）
    day_start: time = Field(default=time(9, 30, 0), title="日起始时间")  # K线锚点时间
    trade_start_time: time = Field(default=time(10, 0, 0), title="交易开始时间")
    trade_end_time: time = Field(default=time(13, 25, 0), title="交易结束时间")
    # 外部信号过滤
    dir_thr: float = Field(default=0.0, title="方向阈值")  # 信号方向阈值
    use_signal: bool = Field(default=True, title="使用外部信号")  # 是否使用外部信号


class RsiStrategy(BaseStrategy):
    """
    RSI 策略
    """

    def __init__(self, strategy_id: str, strategy_config: StrategyConfig):
        super().__init__(strategy_id, strategy_config)
        logger.info(f"RSI策略 [{strategy_id}] 初始化完成")

    def init(self,trading_day: datetime) -> bool:
        """策略初始化，将配置字典转换为RsiParam"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        #基础变量
        self.signal = None
        self._pending_cmd = None
        self._hist_cmds = {}
        self.pos_volume = 0
        self.pos_price = None
        self.trading_day = trading_day

        # 本策略临时变量
        self.minute_bars: deque = deque(maxlen=1000)  # 1分钟K线缓存（用于K线重采样）
        self.short_k_bars: deque = deque(maxlen=200)  # 短周期K线（short_k分钟）
        self.long_k_bars: deque = deque(maxlen=100)  # 长周期K线（long_k分钟）
        self._last_short_bar_time: Optional[datetime] = None
        self._last_long_bar_time: Optional[datetime] = None
        self._long_bar_buf: List[BarData] = []  # 长周期K线缓存
        self._short_bar_buf: List[BarData] = []  # 短周期K线缓存

        # 创建RsiParam实例
        if self.config.params:
            self.param:RsiParam = RsiParam(**self.config.params)
            self.symbol = self.param.symbol

        # 加载上一个交易日的数据
        hist_bars = self.load_hist_bars(
            self.symbol,
            self.trading_day-timedelta(days=3),
            self.trading_day,
        )
        for bar in hist_bars:
            self._resample_kline(bar)

        self.inited = True
        logger.info(f"策略 [{self.strategy_id}] 初始化完成")
        return True


    def update_params(self, params: dict) -> None:
        """
        更新策略参数（只更新内存，不写入文件）
        Args:
            params: 要更新的参数字典
        """
        for key, value in params.items():
            if hasattr(self.param, key):
                # 处理时间类型的参数
                if key in [
                    "trade_start_time",
                    "trade_end_time",
                    "force_exit_time",
                    "day_start",
                ] and isinstance(value, str):
                    value = _parse_time(value)
                setattr(self.param, key, value)
            else:
                logger.warning(f"策略 [{self.strategy_id}] 参数 {key} 不存在")

        logger.info(f"策略 [{self.strategy_id}] 参数已更新: {params}")
    
    async def on_tick(self, tick):
        """Tick行情回调（暂不使用）"""
        await self.execute_signal()
        pass

    async def on_bar(self, bar: BarData):
        """K线行情回调"""

        try:
            # 只处理指定合约的K线
            if bar.symbol != self.param.symbol:
                return

            logger.info(
                f"策略 [{self.strategy_id}] 收到新bar: {bar.symbol} {bar.interval} {bar.datetime} open：{bar.open_price} close:{bar.close_price} update:{bar.update_time} type:{bar.type}"
            )
            # 重新生成K线
            short_bar, long_bar = self._resample_kline(bar)

            bar_time = bar.datetime.time()
            # 强制平仓检查（使用原始K线时间）
            if self.signal and not self.signal.exit_time and bar_time >= self.param.force_exit_time:
                self.signal.exit_price = bar.close_price
                self.signal.exit_time = bar.datetime
                self.signal.exit_reason = "FORCE"
                logger.info(f"策略 [{self.strategy_id}] 信号结束: {self.signal}")

            # 止盈止损检查
            if self.signal and not self.signal.exit_time :
                exit_reason = self._check_exit_conditions(bar.close_price, self.signal)
                if exit_reason:
                    self.signal.exit_price = bar.close_price
                    self.signal.exit_time = bar.datetime
                    self.signal.exit_reason = exit_reason
                    logger.info(f"策略 [{self.strategy_id}] 信号结束: {self.signal}")

            if self.signal:
                # 已经有信号了，当天不再产生新信号了
                return
       
            # 每次产生新的short_bar，进行后续信号计算
            if short_bar is None:
                return

            # 检查交易窗口（使用重采样后的短K线时间）
            if not (self.param.trade_start_time <= short_bar.datetime.time() < self.param.trade_end_time):
                return

            # 计算RSI并生成信号
            side = self._generate_signal(short_bar)
            # 检查信号有效性
            if side == 0 or not self._check_external_signal_filter(side):
                return

            # 记录信号
            self.signal = Signal(
                side=side,
                entry_price=bar.close_price,
                entry_time=bar.datetime,
            )
            logger.info(f"策略 [{self.strategy_id}] 信号开始: {self.signal}")
        except Exception as e:
            logger.exception(f"策略 [{self.strategy_id}] on_bar 异常: {e}")


    def _resample_kline(self, bar: BarData) -> tuple[BarData, BarData]:
        """
        K线重采样（09:30锚定）

        只有在收集齐该时间段内所有M1 bar后才产生新的重采样bar。
        例如M5需要收集齐9:30-9:34的5根M1 bar后，才产生9:30的M5 bar。

        Returns:
            (short_k_bar, long_k_bar) 或 (None, None) 如果还不能形成K线
        """

        bar_time = bar.datetime.time()

        # 计算分钟索引（从09:30开始）
        minute_of_day = bar_time.hour * 60 + bar_time.minute
        anchor_minute = self.param.day_start.hour * 60 + self.param.day_start.minute
        min_idx = minute_of_day - anchor_minute

        # 跳过09:30之前的数据
        if min_idx < 0:
            return None, None

        # 存储1分钟K线
        self.minute_bars.append(
            {
                "datetime": bar.datetime,
                "open": bar.open_price,
                "high": bar.high_price,
                "low": bar.low_price,
                "close": bar.close_price,
                "volume": bar.volume,
                "min_idx": min_idx,
            }
        )


        short_bar = None
        long_bar = None
        self._short_bar_buf.append(bar)
        self._long_bar_buf.append(bar)
        if (min_idx + 1) % self.param.short_k == 0 and len(self._short_bar_buf)>0:
            # 产生新的shortbar
            short_bar = BarData(
                symbol=bar.symbol,
                interval=bar.interval,
                datetime=bar.datetime,
                open_price=self._short_bar_buf[0].open_price,
                high_price=max(b.high_price for b in self._short_bar_buf),
                low_price=min(b.low_price for b in self._short_bar_buf),
                close_price=self._short_bar_buf[-1].close_price,
                volume=sum(b.volume for b in self._short_bar_buf),
                update_time=bar.update_time,
            )
            self.short_k_bars.append(short_bar)
            self._short_bar_buf.clear()
            logger.info(f"策略 [{self.strategy_id}] 产生新的short_bar: {short_bar}")
        
        if (min_idx + 1) % self.param.long_k == 0 and len(self._long_bar_buf)>0:
            # 产生新的longbar
            long_bar = BarData(
                symbol=bar.symbol,
                interval=bar.interval,
                datetime=bar.datetime,
                open_price=self._long_bar_buf[0].open_price,
                high_price=max(b.high_price for b in self._long_bar_buf),
                low_price=min(b.low_price for b in self._long_bar_buf),
                close_price=self._long_bar_buf[-1].close_price,
                volume=sum(b.volume for b in self._long_bar_buf),
                update_time=bar.update_time,
            )
            self.long_k_bars.append(long_bar)
            self._long_bar_buf.clear()
            logger.info(f"策略 [{self.strategy_id}] 产生新的long_bar: {long_bar}")
        
        return short_bar, long_bar
            


        # # 判断是否是短周期时间段的最后一根M1 bar
        # # 例如M5: min_idx=4(9:34)时, (4+1)%5==0, 说明收集齐了9:30-9:34的5根bar
        # if (min_idx + 1) % self.param.short_k == 0:
        #     # 找出当前short_k_idx的所有分钟K线
        #     short_bars = [
        #         b for b in self.minute_bars if b["min_idx"] // self.param.short_k == short_k_idx
        #     ]
        #     if len(short_bars) == self.param.short_k:
        #         short_bar = BarData(
        #             symbol=bar.symbol,
        #             interval=bar.interval,
        #             datetime=short_bars[0]["datetime"],
        #             open_price=short_bars[0]["open"],
        #             high_price=max(b["high"] for b in short_bars),
        #             low_price=min(b["low"] for b in short_bars),
        #             close_price=short_bars[-1]["close"],
        #             volume=sum(b["volume"] for b in short_bars),
        #             update_time=bar.update_time,
        #         )

        # # 判断是否是长周期时间段的最后一根M1 bar
        # if (min_idx + 1) % self.param.long_k == 0:
        #     # 找出当前long_k_idx的所有分钟K线
        #     long_bars = [
        #         b for b in self.minute_bars if b["min_idx"] // self.param.long_k == long_k_idx
        #     ]
        #     if len(long_bars) == self.param.long_k:
        #         long_bar = BarData(
        #             symbol=bar.symbol,
        #             interval=bar.interval,
        #             datetime=long_bars[0]["datetime"],
        #             open_price=long_bars[0]["open"],
        #             high_price=max(b["high"] for b in long_bars),
        #             low_price=min(b["low"] for b in long_bars),
        #             close_price=long_bars[-1]["close"],
        #             volume=sum(b["volume"] for b in long_bars),
        #             update_time=bar.update_time,
        #         )

        # return self._cache_resampled_bars(short_bar, long_bar)

    def _cache_resampled_bars(
        self, short_bar: Optional[BarData], long_bar: Optional[BarData]
    ) -> tuple[Optional[BarData], Optional[BarData]]:
        """
        缓存重采样后的K线（只在新K线完成时添加）

        Args:
            short_bar: 短周期K线（可能为None）
            long_bar: 长周期K线（可能为None）

        Returns:
            (new_short_bar, new_long_bar) 新缓存的K线，如果没有则为None
        """
        new_short_bar = None
        new_long_bar = None

        # 缓存短周期K线
        if short_bar is not None:
            if self._last_short_bar_time is None or short_bar.datetime != self._last_short_bar_time:
                self.short_k_bars.append(short_bar)
                self._last_short_bar_time = short_bar.datetime
                new_short_bar = short_bar
                logger.info(f"缓存新短周期K线: {short_bar}")

        # 缓存长周期K线
        if long_bar is not None:
            if self._last_long_bar_time is None or long_bar.datetime != self._last_long_bar_time:
                self.long_k_bars.append(long_bar)
                self._last_long_bar_time = long_bar.datetime
                new_long_bar = long_bar
                logger.info(f"缓存新长周期K线: {long_bar}")

        return new_short_bar, new_long_bar

    
    def _generate_signal(self, short_bar: BarData) -> int:
        """
        生成交易信号

        Args:
            short_bar: 短周期K线
            long_bar: 长周期K线

        Returns:
            signal: 交易信号 (1-开多 -1-开空 0-无信号)
        """
        # 使用K线收盘价计算RSI
        # 需要足够的历史数据
        min_bars_needed = self.param.rsi_n + 1
        if len(self.short_k_bars) < min_bars_needed:
            return 0

        # 短周期RSI计算
        short_prices = [b.close_price for b in list(self.short_k_bars)[-min_bars_needed:]]
        rsi_short = calc_rsi_sma(short_prices, self.param.rsi_n)

        # 长周期RSI计算
        long_prices = [b.close_price for b in list(self.long_k_bars)[-min_bars_needed:]]
        rsi_long = calc_rsi_sma(long_prices, self.param.rsi_n)

        if not np.isfinite(rsi_short) or not np.isfinite(rsi_long):
            return 0

        # 多头信号：长周期RSI > long_threshold 且 短周期RSI > short_threshold
        if rsi_long > self.param.long_threshold and rsi_short > self.param.short_threshold:
            logger.info(f"RSI多头信号: rsi_long={rsi_long:.2f}, rsi_short={rsi_short:.2f}")
            return 1

        # 空头信号：长周期RSI < (100-long_threshold) 且 短周期RSI < (100-short_threshold)
        if rsi_long < (100 - self.param.long_threshold) and rsi_short < (
            100 - self.param.short_threshold
        ):
            logger.info(f"RSI空头信号: rsi_long={rsi_long:.2f}, rsi_short={rsi_short:.2f}")
            return -1

        return 0

    def _check_external_signal_filter(self, side: int) -> bool:
        """
        检查外部信号方向过滤

        Args:
            side: 交易方向 (1多头, -1空头)

        Returns:
            bool: 是否通过过滤
        """
        if not self.param or not self.param.use_signal:
            return True

        ext_signal = self.param.use_signal
        dir_thr = self.param.dir_thr

        # 根据阈值确定外部方向
        if ext_signal >= dir_thr:
            ext_dir = 1
        elif ext_signal <= -dir_thr:
            ext_dir = -1
        else:
            ext_dir = 0

        # 检查是否匹配
        if ext_dir == 0:
            # 信号方向为0，当天不交易
            logger.debug(f"策略 [{self.strategy_id}] 外部信号为0，不交易")
            return False

        if ext_dir != side:
            # 方向不匹配
            logger.debug(
                f"策略 [{self.strategy_id}] 方向不匹配: RSI方向={side}, 外部方向={ext_dir}"
            )
            return False

        return True

    def _check_exit_conditions(self, current_price: float, signal: Signal) -> str:
        """
        检查止盈止损条件

        Args:
            current_price: 当前价格

        Returns:
            退出原因 ("TP"/"SL"/None)
        """
        open_price = self.pos_price or signal.entry_price
        if signal.side == 1:
            # 多头仓位
            profit_pct = (current_price - open_price) / open_price
            if profit_pct >= self.param.take_profit_pct:
                return "TP"
            if profit_pct <= -self.param.stop_loss_pct:
                return "SL"
        else:
            # 空头仓位
            profit_pct = (open_price - current_price) / open_price
            if profit_pct >= self.param.take_profit_pct:
                return "TP"
            if profit_pct <= -self.param.stop_loss_pct:
                return "SL"

        return None


def roll_mean_right(values: list, n: int) -> float:
    """右对齐滚动均值（忽略非有限值）"""
    a = np.array(values, dtype=float)
    L = a.shape[0]

    if n <= 0 or L < n:
        return np.nan
    if n == 1:
        return a[-1]

    # 识别有效（有限）值
    finite_mask = np.isfinite(a)
    a2 = np.where(finite_mask, a, 0.0)

    # 计算累积和和累积计数
    cs = np.concatenate(([0.0], np.cumsum(a2)))
    cn = np.concatenate(([0], np.cumsum(finite_mask.astype(int))))

    # 计算滚动均值
    s = cs[L] - cs[L - n]
    k = cn[L] - cn[L - n]

    if k <= 0:
        return np.nan
    return s / k


def calc_rsi_sma(values: list, n: int) -> float:
    """使用 SMA 口径的 RSI"""

    c = np.array(values, dtype=float)
    d = np.diff(c)

    # 分离上涨和下跌幅度
    U = np.maximum(d, 0)
    D = np.maximum(-d, 0)

    # 计算上涨和下跌的滚动均值
    AU = roll_mean_right(U.tolist(), n)
    AD = roll_mean_right(D.tolist(), n)

    if not np.isfinite(AU) or not np.isfinite(AD):
        return np.nan

    # 计算相对强度
    RS = AU / max(AD, EPS)

    # 转换为RSI值
    return 100.0 * RS / (1.0 + RS)
