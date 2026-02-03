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
from datetime import datetime, time
from typing import Optional

import numpy as np
from pydantic import BaseModel

from src.models.object import BarData, Offset
from src.trader.strategy.base_strategy import BaseStrategy
from src.utils.config_loader import StrategyConfig
from src.utils.logger import get_logger
from src.utils.helpers import _get_float_param, _get_bool_param, _get_str_param, _get_int_param, _parse_time

logger = get_logger(__name__)

# 数值计算精度控制
EPS = 1e-12


class RsiParam(BaseModel):
    """RSI策略参数"""

    symbol: str = ""
    exchange: str = "DCE"
    volume_per_trade: int = 1
    max_position: int = 5
    # RSI参数
    rsi_n: int = 5  # RSI计算周期
    short_k: int = 5  # 短K线周期（分钟）
    long_k: int = 15  # 长K线周期（分钟）
    # RSI阈值
    long_threshold: float = 50.0  # 长RSI多头阈值 (对应原L)
    short_threshold: float = 55.0  # 短RSI多头阈值 (对应原S)
    # 交易时间窗口
    day_start: time = time(9, 30, 0)  # K线锚点时间
    trade_start_time: time = time(10, 0, 0)
    trade_end_time: time = time(13, 25, 0)
    force_exit_time: time = time(14, 55, 0)
    # 风控参数
    take_profit_pct: float = 0.015  # 止盈比例
    stop_loss_pct: float = 0.015  # 止损比例
    # 外部信号过滤
    dir_thr: float = 0.0  # 信号方向阈值
    use_signal: bool = True  # 是否使用外部信号
    # 手续费率
    fee_rate: float = 0.0001  # 每笔手续费率
    # K线重采样锚点
    anchor_time: time = time(9, 30, 0)


class RsiStrategy(BaseStrategy):
    """
    RSI 策略
    """

    def __init__(self, strategy_id: str, strategy_config: StrategyConfig):
        super().__init__(strategy_id, strategy_config)
        logger.info(f"RSI策略 [{strategy_id}] 初始化完成")

    def init(self) -> bool:
        """策略初始化，将配置字典转换为RsiParam"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        # 状态变量
        self.close_prices: deque = deque(maxlen=500)  # 存储收盘价（用于计算RSI）
        self.minute_bars: deque = deque(maxlen=1000)  # 1分钟K线缓存（用于K线重采样）
        self.short_k_bars: deque = deque(maxlen=200)  # 短周期K线（short_k分钟）
        self.long_k_bars: deque = deque(maxlen=100)  # 长周期K线（long_k分钟）
        # 持仓状态
        self.position_side = 0  # 持仓方向: 1多头, -1空头,0无持仓
        self.position_volume = 0  # 当前持仓量
        self.entry_price = 0.0  # 开仓价格
        self.entry_bar_time = None  # 开仓K线时间
        # 交易控制
        self.last_trade_date =  datetime.now().strftime("%Y-%m-%d")  # 最后交易日期
        self.pending_signal = None  # 待执行的信号（next-bar-open机制）
        self.pending_side = 0  # 待执行的方向
        self.signal_bar_time = None  # 信号产生的时间

        # 收益统计
        self.trade_count = 0  # 交易次数
        self.total_pnl = 0.0  # 总盈亏

        # 构建参数字典，支持CSV和YAML两种格式的参数名
        # 注意：CSV中的列名可能是小写，这里需要兼容
        param_dict = self.config.params
        param_dict_for_rsi = {
            "symbol": param_dict.get("symbol", ""),
            "volume_per_trade": _get_int_param(param_dict, ["volume", "volume_per_trade"], 1),
            "max_position": _get_int_param(param_dict, ["max_position"], 5),
            # RSI参数（统一命名）
            "rsi_n": _get_int_param(param_dict, ["rsi_n", "rsi_period"], 5),
            "short_k": _get_int_param(param_dict, ["short_k", "short_kline_period"], 5),
            "long_k": _get_int_param(param_dict, ["long_k", "long_kline_period"], 15),
            "long_threshold": _get_float_param(param_dict, ["long_threshold", "L", "rsi_long_threshold"], 50.0),
            "short_threshold": _get_float_param(param_dict, ["short_threshold", "S", "rsi_short_threshold"], 55.0),
            # 交易时间
            "trade_start_time": _parse_time(_get_str_param(param_dict, ["trade_start_time"], "10:00:00")),
            "trade_end_time": _parse_time(_get_str_param(param_dict, ["trade_end_time"], "13:25:00")),
            "force_exit_time": _parse_time(_get_str_param(param_dict, ["force_exit_time"], "14:55:00")),
            "day_start": _parse_time(_get_str_param(param_dict, ["day_start"], "09:30:00")),
            # 风控参数
            "take_profit_pct": _get_float_param(param_dict, ["tp_ret", "take_profit_pct"], 0.015),
            "stop_loss_pct": _get_float_param(param_dict, ["sl_ret", "stop_loss_pct"], 0.015),
            # 外部信号参数
            "dir_thr": _get_float_param(param_dict, ["dir_thr"], 0.0),
            "use_signal": _get_bool_param(param_dict, ["used_signal", "use_signal"], True),
            # 其他参数
            "one_trade_per_day": _get_bool_param(param_dict, ["one_trade_per_day"], True),
            "fee_rate": _get_float_param(param_dict, ["fee_rate"], 0.0001),
        }
        # 创建RsiParam实例
        self.rsi_param = RsiParam(**param_dict_for_rsi)
        # 更新合约代码
        self.config.symbol = self.rsi_param.symbol

        logger.info(f"策略 [{self.strategy_id}] 初始化完成")
        return True

    def get_params(self) -> dict:
        """获取策略参数"""
        return self.rsi_param.model_dump()
    

    def _is_in_trade_window(self, bar_time: time) -> bool:
        """判断是否在交易窗口内"""
        return self.rsi_param.trade_start_time <= bar_time < self.rsi_param.trade_end_time

    def _is_force_exit_time(self, bar_time: time) -> bool:
        """判断是否需要强制平仓"""
        return bar_time >= self.rsi_param.force_exit_time

    def _can_trade_today(self, bar: BarData) -> bool:
        """判断今天是否可以交易"""
        trade_date = bar.datetime.strftime("%Y-%m-%d")
        return self.last_trade_date != trade_date

    def _resample_kline(self, bar: BarData) -> tuple[BarData, BarData]:
        """
        K线重采样（09:30锚定）

        Returns:
            (short_k_bar, long_k_bar) 或 (None, None) 如果还不能形成K线
        """
        if not self.rsi_param:
            return None, None

        bar_time = bar.datetime.time()

        # 计算分钟索引（从09:30开始）
        minute_of_day = bar_time.hour * 60 + bar_time.minute
        anchor_minute = self.rsi_param.day_start.hour * 60 + self.rsi_param.day_start.minute
        min_idx = minute_of_day - anchor_minute

        # 跳过09:30之前的数据
        if min_idx < 0:
            return None, None

        # 存储1分钟K线
        self.minute_bars.append({
            'datetime': bar.datetime,
            'open': bar.open_price,
            'high': bar.high_price,
            'low': bar.low_price,
            'close': bar.close_price,
            'volume': bar.volume,
            'min_idx': min_idx,
        })

        # 检查是否可以形成新的短周期K线
        short_k_idx = min_idx // self.rsi_param.short_k
        long_k_idx = min_idx // self.rsi_param.long_k

        # 短周期K线
        short_bar = None
        if len(self.minute_bars) >= 1:
            # 找出当前short_k_idx的所有分钟K线
            short_bars = [b for b in self.minute_bars if b['min_idx'] // self.rsi_param.short_k == short_k_idx]
            if short_bars:
                short_bar = BarData(
                    symbol=bar.symbol,
                    interval = bar.interval,
                    datetime=short_bars[0]['datetime'],
                    open_price=short_bars[0]['open'],
                    high_price=max(b['high'] for b in short_bars),
                    low_price=min(b['low'] for b in short_bars),
                    close_price=short_bars[-1]['close'],
                    volume=sum(b['volume'] for b in short_bars),
                )

        # 长周期K线
        long_bar = None
        if len(self.minute_bars) >= 1:
            long_bars = [b for b in self.minute_bars if b['min_idx'] // self.rsi_param.long_k == long_k_idx]
            if long_bars:
                long_bar = BarData(
                    symbol=bar.symbol,
                    interval = bar.interval,
                    datetime=long_bars[0]['datetime'],
                    open_price=long_bars[0]['open'],
                    high_price=max(b['high'] for b in long_bars),
                    low_price=min(b['low'] for b in long_bars),
                    close_price=long_bars[-1]['close'],
                    volume=sum(b['volume'] for b in long_bars),
                )

        return short_bar, long_bar


    

    def on_tick(self, tick):
        """Tick行情回调（暂不使用）"""
        pass

    def on_bar(self, bar: BarData):
        """K线行情回调"""

        if not self.active or not self.rsi_param:
            return

        try:
            # 只处理指定合约的K线
            if bar.symbol != self.rsi_param.symbol:
                return
            
            logger.info(f"策略 [{self.strategy_id}] 收到新bar: {bar.symbol} {bar.interval} {bar.datetime}")

            bar_time = bar.datetime.time()
            # K线重采样（09:30锚定）
            short_bar, long_bar = self._resample_kline(bar)
            if short_bar is None or long_bar is None:
                return

            # 获取重采样后K线的时间
            short_time = short_bar.datetime.time()

            # 强制平仓检查（使用原始K线时间）
            if self.position_side != 0 and self._is_force_exit_time(bar_time):
                self._close_position("FORCE_EXIT", bar)
                return

            # 止盈止损检查
            if self.position_side != 0:
                exit_reason = self._check_exit_conditions(bar.close_price)
                if exit_reason:
                    self._close_position(exit_reason, bar)
                    return

            # 检查交易窗口（使用重采样后的短K线时间）
            if not self._is_in_trade_window(short_time):
                return

            # 检查每天只能交易一次
            if  self.trade_count > 0:
                return
            
            # 计算RSI并生成信号
            signal= self._generate_signal(short_bar, long_bar)
            # 检查信号有效性
            if signal == 0 or not self._check_external_signal_filter(signal):
                return

            self._open_position(signal, short_bar.open_price, short_bar)
        except Exception as e:
            logger.exception(f"策略 [{self.strategy_id}] on_bar 异常: {e}")

    def _generate_signal(self, short_bar: BarData, long_bar: BarData) -> int:
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
        min_bars_needed = self.rsi_param.rsi_n + 1

        # 短周期RSI计算
        if len(self.short_k_bars) < min_bars_needed:
            return 0
        short_prices = [b.close_price for b in list(self.short_k_bars)[-min_bars_needed:]]
        rsi_short = calc_rsi_sma(short_prices, self.rsi_param.rsi_n)

        # 长周期RSI计算
        if len(self.long_k_bars) < min_bars_needed:
            return 0
        long_prices = [b.close_price for b in list(self.long_k_bars)[-min_bars_needed:]]
        rsi_long = calc_rsi_sma(long_prices, self.rsi_param.rsi_n)

        if not np.isfinite(rsi_short) or not np.isfinite(rsi_long):
            return 0

        # 多头信号：长周期RSI > long_threshold 且 短周期RSI > short_threshold
        if rsi_long > self.rsi_param.long_threshold and rsi_short > self.rsi_param.short_threshold:
            logger.debug(f"RSI多头信号: rsi_long={rsi_long:.2f}, rsi_short={rsi_short:.2f}")
            return 1

        # 空头信号：长周期RSI < (100-long_threshold) 且 短周期RSI < (100-short_threshold)
        if rsi_long < (100 - self.rsi_param.long_threshold) and rsi_short < (100 - self.rsi_param.short_threshold):
            logger.debug(f"RSI空头信号: rsi_long={rsi_long:.2f}, rsi_short={rsi_short:.2f}")
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
        if not self.rsi_param or not self.rsi_param.use_signal:
            return True

        ext_signal = self.rsi_param.use_signal
        dir_thr = self.rsi_param.dir_thr

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
            logger.debug(f"策略 [{self.strategy_id}] 方向不匹配: RSI方向={side}, 外部方向={ext_dir}")
            return False

        return True

    def _open_position(self, side: int, price: float, bar: BarData):
        """
        开仓

        Args:
            side: 1多头, -1空头
            price: 入场价格
            bar: 当前K线
        """
        if not self.rsi_param:
            return

        try:
            if side == 1:
                # 开多仓
                order_id = self.buy(
                    symbol=f"{self.rsi_param.exchange}.{self.rsi_param.symbol}",
                    volume=self.rsi_param.volume_per_trade,
                    price=price,
                    offset=Offset.OPEN,
                )
                if order_id:
                    self.position_side = 1
                    self.entry_price = price
                    self.entry_bar_time = bar.datetime
                    self.trade_count += 1
                    logger.info(f"开多仓: price={price}, order_id={order_id}")
            elif side == -1:
                # 开空仓
                order_id = self.sell(
                    symbol=f"{self.rsi_param.exchange}.{self.rsi_param.symbol}",
                    volume=self.rsi_param.volume_per_trade,
                    price=price,
                    offset=Offset.OPEN,
                )
                if order_id:
                    self.position_side = -1
                    self.entry_price = price
                    self.entry_bar_time = bar.datetime
                    self.trade_count += 1
                    logger.info(f"开空仓: price={price}, order_id={order_id}")
        except Exception as e:
            logger.error(f"执行交易失败: {e}", exc_info=True)

    def _close_position(self, reason: str, bar: BarData):
        """
        平仓

        Args:
            reason: 平仓原因 (TP/SL/FORCE_EXIT/EXIT_TIME)
            bar: 当前K线
        """
        if self.position_side == 0:
            return

        try:
            exit_price = bar.close_price
            symbol = f"{self.rsi_param.exchange}.{self.rsi_param.symbol}"
            volume = self.rsi_param.volume_per_trade

            if self.position_side == 1:
                # 平多仓 (卖出平仓)
                order_id = self.sell(symbol=symbol, volume=volume, price=exit_price, offset=Offset.CLOSE)
            else:
                # 平空仓 (买入平仓)
                order_id = self.buy(symbol=symbol, volume=volume, price=exit_price, offset=Offset.CLOSE)

            # 计算盈亏
            if self.position_side == 1:
                pnl = (exit_price - self.entry_price) * volume
            else:
                pnl = (self.entry_price - exit_price) * volume

            self.total_pnl += pnl

            logger.info(
                f"平仓 [{reason}]: side={self.position_side}, entry={self.entry_price:.2f}, "
                f"exit={exit_price:.2f}, pnl={pnl:.2f}, order_id={order_id}"
            )

            # 重置持仓状态
            self.position_side = 0
            self.entry_price = 0.0
            self.entry_bar_time = None
            self.pending_signal = None
            self.pending_side = 0
            self.signal_bar_time = None

        except Exception as e:
            logger.error(f"平仓失败: {e}", exc_info=True)

    def _check_exit_conditions(self, current_price: float) -> str:
        """
        检查止盈止损条件

        Args:
            current_price: 当前价格

        Returns:
            退出原因 ("TP"/"SL"/None)
        """
        if self.position_side == 0 or not self.rsi_param:
            return None

        entry_price = self.entry_price

        if self.position_side == 1:
            # 多头仓位
            profit_pct = (current_price - entry_price) / entry_price
            if profit_pct >= self.rsi_param.take_profit_pct:
                return "TP"
            if profit_pct <= -self.rsi_param.stop_loss_pct:
                return "SL"
        else:
            # 空头仓位
            profit_pct = (entry_price - current_price) / entry_price
            if profit_pct >= self.rsi_param.take_profit_pct:
                return "TP"
            if profit_pct <= -self.rsi_param.stop_loss_pct:
                return "SL"

        return None

    def _is_exit_time(self, bar_time: time) -> bool:
        """
        判断是否超出交易时间（用于阻止新的入场）

        Args:
            bar_time: K线时间

        Returns:
            bool: 是否超出交易时间
        """
        if not self.rsi_param:
            return True
        return bar_time >= self.rsi_param.trade_end_time

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
    if len(values) < n + 1:
        return np.nan

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