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
from datetime import datetime, time, timedelta
from turtle import pos
from typing import Optional

import numpy as np
from pydantic import BaseModel
from pydantic_core.core_schema import NoneSchema

from src.models.object import BarData, OrderData,Offset
from src.trader.strategy.base_strategy import BaseStrategy
from src.utils.config_loader import StrategyConfig
from src.utils.logger import get_logger
from src.utils.helpers import _get_float_param, _get_bool_param, _get_str_param, _get_int_param, _parse_time
from src.trader.order_cmd import OrderCmd

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

class Signal(BaseModel):
    """交易信号"""
    enable: bool = True  # 是否有效
    strategy_id: str = ""
    side: int = 0  # 信号方向: 1多头, -1空头,0无信号
    entry_price: float = 0.0  # 开仓价格
    entry_time: datetime = None  # 开仓时间
    entry_volume: int = 0  # 开仓目标手数
    exit_price: float = 0.0  # 平仓价格
    exit_time: datetime = None  # 平仓时间
    exit_reason: str = ""  # 平仓原因
    rsi: float = 0.0  # 当前RSI值

    # 真实入场信息
    entry_order_id: Optional[str] = None  # 开仓订单信息
    exit_order_id: Optional[str] = None  # 平仓订单信息
    pos_volume: int = 0     # 持仓手数
    pos_price: float|None = None # 持仓均价


    def __str__(self) -> str:
        return (f"Signal(strategy_id={self.strategy_id}, side={self.side}, "
                f"entry_price={self.entry_price}, entry_time={self.entry_time}, exit_price={self.exit_price}, "
                f"exit_time={self.exit_time}, exit_reason={self.exit_reason})")


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
        self.minute_bars: deque = deque(maxlen=1000)  # 1分钟K线缓存（用于K线重采样）
        self.short_k_bars: deque = deque(maxlen=200)  # 短周期K线（short_k分钟）
        self.long_k_bars: deque = deque(maxlen=100)  # 长周期K线（long_k分钟）
        # 用于检测新K线的缓存
        self._last_short_bar_time: Optional[datetime] = None
        self._last_long_bar_time: Optional[datetime] = None
        # 交易信号
        self.signal = None
        self.order_cmds: dict[str, OrderCmd] = {}

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

        # 计算当前bar所属的周期索引
        short_k_idx = min_idx // self.rsi_param.short_k
        long_k_idx = min_idx // self.rsi_param.long_k

        short_bar = None
        long_bar = None

        # 判断是否是短周期时间段的最后一根M1 bar
        # 例如M5: min_idx=4(9:34)时, (4+1)%5==0, 说明收集齐了9:30-9:34的5根bar
        if (min_idx + 1) % self.rsi_param.short_k == 0:
            # 找出当前short_k_idx的所有分钟K线
            short_bars = [b for b in self.minute_bars if b['min_idx'] // self.rsi_param.short_k == short_k_idx]
            if len(short_bars) == self.rsi_param.short_k:
                short_bar = BarData(
                    symbol=bar.symbol,
                    interval=bar.interval,
                    datetime=short_bars[0]['datetime'],
                    open_price=short_bars[0]['open'],
                    high_price=max(b['high'] for b in short_bars),
                    low_price=min(b['low'] for b in short_bars),
                    close_price=short_bars[-1]['close'],
                    volume=sum(b['volume'] for b in short_bars),
                    update_time=bar.datetime,
                )

        # 判断是否是长周期时间段的最后一根M1 bar
        if (min_idx + 1) % self.rsi_param.long_k == 0:
            # 找出当前long_k_idx的所有分钟K线
            long_bars = [b for b in self.minute_bars if b['min_idx'] // self.rsi_param.long_k == long_k_idx]
            if len(long_bars) == self.rsi_param.long_k:
                long_bar = BarData(
                    symbol=bar.symbol,
                    interval=bar.interval,
                    datetime=long_bars[0]['datetime'],
                    open_price=long_bars[0]['open'],
                    high_price=max(b['high'] for b in long_bars),
                    low_price=min(b['low'] for b in long_bars),
                    close_price=long_bars[-1]['close'],
                    volume=sum(b['volume'] for b in long_bars),
                    update_time=bar.datetime+timedelta(minutes=1),
                )

        return self._cache_resampled_bars(short_bar, long_bar)

    def _cache_resampled_bars(self, short_bar: Optional[BarData], long_bar: Optional[BarData]) -> tuple[Optional[BarData], Optional[BarData]]:
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


    def on_tick(self, tick):
        """Tick行情回调（暂不使用）"""
        pass

    def on_bar(self, bar: BarData):
        """K线行情回调"""

        try:
            # 只处理指定合约的K线
            if bar.symbol != self.rsi_param.symbol:
                return

            

            logger.info(f"策略 [{self.strategy_id}] 收到新bar: {bar.symbol} {bar.interval} {bar.datetime} open：{bar.open_price} close:{bar.close_price} type:{bar.type}")

            bar_time = bar.datetime.time()
            # 强制平仓检查（使用原始K线时间）
            if self.signal and not self.signal.exit_time and self._is_force_exit_time(bar_time):
                self.signal.exit_price = bar.close_price
                self.signal.exit_time = bar.datetime
                self.signal.exit_reason = "FORCE"
                logger.info(f"策略 [{self.strategy_id}] 信号结束: {self.signal}")

            # 止盈止损检查
            if self.signal and not self.signal.exit_time:
                exit_reason = self._check_exit_conditions(bar.close_price,self.signal)
                if exit_reason:
                    self.signal.exit_price = bar.close_price
                    self.signal.exit_time = bar.datetime
                    self.signal.exit_reason = exit_reason
                    logger.info(f"策略 [{self.strategy_id}] 信号结束: {self.signal}")


            if self.signal:
                self._execute_signal(bar,self.signal)
                #已经有信号了，当天不再产生新信号了
                return

            # K线重采样（09:30锚定）
            short_bar, long_bar = self._resample_kline(bar)
            # 每次产生新的long_bar，进行后续信号计算
            if long_bar is None:
                return
    
            # 检查交易窗口（使用重采样后的短K线时间）
            if not self._is_in_trade_window(short_bar.datetime.time()):
                return

            # 计算RSI并生成信号
            side= self._generate_signal(short_bar)
            # 检查信号有效性
            if side == 0 or not self._check_external_signal_filter(side):
                return
                
            # 记录信号
            self.signal = Signal(
               strategy_id=self.strategy_id,
               side=side,
               entry_price=short_bar.close_price,
               entry_time=short_bar.datetime,
            )
            logger.info(f"策略 [{self.strategy_id}] 信号开始: {self.signal}")
            self._execute_signal(bar, self.signal)

        except Exception as e:
            logger.exception(f"策略 [{self.strategy_id}] on_bar 异常: {e}")

    def on_order(self, order: OrderData):
        """订单状态回调"""
        if not self.signal:
            return      
        if not order.status == "FINISHED":
            return 

        if  self.signal.entry_order and order.order_id != self.signal.entry_order.order_id:
            # 开仓报单回报
            self.signal.entry_order = None
            total_cost = order.traded * order.price+self.signal.pos_volume*self.signal.pos_price
            self.signal.pos_volume += order.traded
            self.signal.pos_price = total_cost/self.signal.pos_volume
            return 
        if self.signal.exit_order and order.order_id == self.signal.exit_order.order_id:
            # 平仓报单回报
            self.signal.exit_order = None
            self.signal.pos_volume -= order.traded
            return 

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
        min_bars_needed = self.rsi_param.rsi_n+1
        if len(self.long_k_bars) < min_bars_needed:
            return 0

        # 短周期RSI计算
        short_prices = [b.close_price for b in list(self.short_k_bars)[-min_bars_needed:]]
        rsi_short = calc_rsi_sma(short_prices, self.rsi_param.rsi_n)

        # 长周期RSI计算
        long_prices = [b.close_price for b in list(self.long_k_bars)[-min_bars_needed:]]
        rsi_long = calc_rsi_sma(long_prices, self.rsi_param.rsi_n)

        if not np.isfinite(rsi_short) or not np.isfinite(rsi_long):
            return 0

        # 多头信号：长周期RSI > long_threshold 且 短周期RSI > short_threshold
        if rsi_long > self.rsi_param.long_threshold and rsi_short > self.rsi_param.short_threshold:
            logger.info(f"RSI多头信号: rsi_long={rsi_long:.2f}, rsi_short={rsi_short:.2f}")
            return 1

        # 空头信号：长周期RSI < (100-long_threshold) 且 短周期RSI < (100-short_threshold)
        if rsi_long < (100 - self.rsi_param.long_threshold) and rsi_short < (100 - self.rsi_param.short_threshold):
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

    
    def _execute_signal(self, bar: BarData, signal: Signal):
        """
        执行交易信号

        Args:
            bar: 当前K线
            signal: 交易信号
        """
        if signal.exit_time:
            # 平仓处理
            if signal.entry_order_id:
                entry_cmd = self.order_cmds[signal.entry_order_id]
                if not entry_cmd.is_finished:
                    self.cancel_order_cmd(entry_cmd)
                
            if not signal.exit_order_id:
                exit_cmd = OrderCmd(
                    symbol=f"{self.rsi_param.exchange}.{self.rsi_param.symbol}",
                    offset=Offset.CLOSE,
                    direction="SELL" if signal.side == 1 else "BUY",
                    volume=self.rsi_param.volume_per_trade,
                    price=bar.close_price,
                )
                signal.exit_order_id = exit_cmd.cmd_id
                self.send_order_cmd(exit_cmd)
        else:
            # 开仓处理
            if not signal.entry_order_id:
                entry_cmd = OrderCmd(
                    symbol=f"{self.rsi_param.exchange}.{self.rsi_param.symbol}",
                    offset=Offset.OPEN,
                    direction="BUY" if signal.side == 1 else "SELL",
                    volume=self.rsi_param.volume_per_trade,
                    price=bar.close_price,
                )
                signal.entry_order_id = entry_cmd.cmd_id
                self.send_order_cmd(entry_cmd)


    def _check_exit_conditions(self, current_price: float,signal:Signal) -> str:
        """
        检查止盈止损条件

        Args:
            current_price: 当前价格

        Returns:
            退出原因 ("TP"/"SL"/None)
        """
        if signal.side == 1:
            # 多头仓位
            profit_pct = (current_price - signal.entry_price) / signal.entry_price
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