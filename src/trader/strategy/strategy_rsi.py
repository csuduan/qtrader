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

from src.models.object import BarData, Offset
from src.trader.strategy.base_strategy import BaseStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 数值计算精度控制
EPS = 1e-12


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


class RsiStrategy(BaseStrategy):
    """
    RSI 策略

    策略参数（从配置文件读取）:
    CSV参数: StrategyId, Product, TradingDay, Symbol, StartTime, EndTime, ForceExitTime, TpRet, SlRet, DirThr, UsedSignal
    YAML参数: symbol, exchange, volume_per_trade, rsi_period, take_profit_pct, stop_loss_pct, 等

    CSV参数会覆盖YAML中同名参数
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        # 从配置读取参数（支持CSV和YAML两种格式）
        self.symbol = config.get("symbol", "")
        self.exchange = config.get("exchange", "DCE")
        self.volume_per_trade = config.get("volume_per_trade", 1)
        self.max_position = config.get("max_position", 5)

        # RSI参数
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_long_threshold = config.get("rsi_long_threshold", 50)
        self.rsi_short_threshold = config.get("rsi_short_threshold", 80)

        # K线周期参数
        self.short_kline_period = config.get("short_kline_period", 5)
        self.long_kline_period = config.get("long_kline_period", 15)

        # 止盈止损（支持CSV的TpRet/SlRet和YAML的take_profit_pct/stop_loss_pct）
        self.take_profit_pct = self._get_float_param(config, ["TpRet", "take_profit_pct"], 0.02)
        self.stop_loss_pct = self._get_float_param(config, ["SlRet", "stop_loss_pct"], 0.01)

        # 交易窗口（支持CSV的StartTime/EndTime/ForceExitTime和YAML的trade_start_time等）
        self.trade_start_time = self._parse_time(
            self._get_str_param(config, ["StartTime", "trade_start_time"], "09:30:00")
        )
        self.trade_end_time = self._parse_time(
            self._get_str_param(config, ["EndTime", "trade_end_time"], "14:50:00")
        )
        self.force_exit_time = self._parse_time(
            self._get_str_param(config, ["ForceExitTime", "force_exit_time"], "14:55:00")
        )

        # 方向阈值（CSV参数）
        self.dir_threshold = self._get_float_param(config, ["DirThr", "dir_threshold"], 0.0)

        # 是否使用信号（CSV参数）
        self.used_signal = self._get_bool_param(config, ["UsedSignal", "used_signal"], True)

        # 交易限制
        self.one_trade_per_day = config.get("one_trade_per_day", True)

        # 状态变量
        self.close_prices: deque = deque(maxlen=500)  # 存储收盘价
        self.short_bar_buffer: list = []  # 短周期K线缓存
        self.long_bar_buffer: list = []  # 长周期K线缓存

        self.holding = False  # 是否持仓
        self.position_side = 0  # 持仓方向: 1多头, -1空头
        self.entry_price = 0.0  # 开仓价格
        self.entry_bar_time = None  # 开仓K线时间

        self.last_trade_date = None  # 最后交易日期

        logger.info(f"RSI策略 [{strategy_id}] 初始化完成，参数: {config}")

    def _get_float_param(self, config: dict, keys: list, default: float) -> float:
        """获取浮点数参数（支持多个key）"""
        for key in keys:
            val = config.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return default

    def _get_str_param(self, config: dict, keys: list, default: str) -> str:
        """获取字符串参数（支持多个key）"""
        for key in keys:
            val = config.get(key)
            if val is not None:
                return str(val)
        return default

    def _get_bool_param(self, config: dict, keys: list, default: bool) -> bool:
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

    def _parse_time(self, time_str: str) -> time:
        """解析时间字符串"""
        try:
            h, m, s = time_str.split(":")
            return time(int(h), int(m), int(s))
        except Exception as e:
            logger.warning(f"时间解析失败: {time_str}, {e}")
            return time(0, 0, 0)

    def _is_in_trade_window(self, bar_time: time) -> bool:
        """判断是否在交易窗口内"""
        return self.trade_start_time <= bar_time < self.trade_end_time

    def _is_force_exit_time(self, bar_time: time) -> bool:
        """判断是否需要强制平仓"""
        return bar_time >= self.force_exit_time

    def _get_trade_date(self, bar: BarData) -> str:
        """获取交易日期"""
        return bar.datetime.strftime("%Y-%m-%d")

    def _can_trade_today(self, bar: BarData) -> bool:
        """判断今天是否可以交易"""
        if not self.one_trade_per_day:
            return True
        trade_date = self._get_trade_date(bar)
        return self.last_trade_date != trade_date

    def init(self) -> bool:
        """策略初始化"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        return True

    def reset_for_new_day(self) -> bool:
        """
        每日开盘重置策略状态

        清除昨日的信号、持仓状态、中间变量等
        """
        logger.info(f"策略 [{self.strategy_id}] 每日重置...")

        # 重置状态变量
        self.close_prices.clear()
        self.short_bar_buffer.clear()
        self.long_bar_buffer.clear()

        # 重置交易状态
        self.holding = False
        self.position_side = 0
        self.entry_price = 0.0
        self.entry_bar_time = None

        # 重置交易日期
        self.last_trade_date = None

        logger.info(f"策略 [{self.strategy_id}] 每日重置完成")
        return True

    def on_tick(self, tick):
        """Tick行情回调（暂不使用）"""
        pass

    def on_bar(self, bar: BarData):
        """K线行情回调"""
        if not self.active:
            return

        try:
            # 只处理指定合约的K线
            if bar.symbol != self.symbol or bar.exchange.value != self.exchange:
                return

            bar_time = bar.datetime.time()

            # 存储收盘价
            self.close_prices.append(bar.close_price)

            # 强制平仓检查
            if self.holding and self._is_force_exit_time(bar_time):
                self._close_position("FORCE_EXIT")
                return

            # 止盈止损检查
            if self.holding:
                exit_reason = self._check_exit_conditions(bar.close_price)
                if exit_reason:
                    self._close_position(exit_reason)
                    return

            # 检查交易窗口
            if not self._is_in_trade_window(bar_time):
                return

            # 检查数据是否足够
            if len(self.close_prices) < self.long_kline_period + self.rsi_period:
                return

            # 计算RSI并生成信号
            signal = self._generate_signal()

            # 执行交易
            if signal != 0 and not self.holding:
                if self._can_trade_today(bar):
                    self._execute_signal(signal, bar)

        except Exception as e:
            logger.error(f"策略 [{self.strategy_id}] on_bar 异常: {e}", exc_info=True)

    def _generate_signal(self) -> int:
        """
        生成交易信号

        Returns:
            int: 1=多头信号, -1=空头信号, 0=无信号
        """
        # 计算短周期RSI
        short_period = min(self.short_kline_period, len(self.close_prices))
        short_prices = list(self.close_prices)[-short_period:]
        rsi_short = calc_rsi_sma(short_prices, self.rsi_period)

        # 计算长周期RSI
        long_period = min(self.long_kline_period, len(self.close_prices))
        long_prices = list(self.close_prices)[-long_period:]
        rsi_long = calc_rsi_sma(long_prices, self.rsi_period)

        if not np.isfinite(rsi_short) or not np.isfinite(rsi_long):
            return 0

        # 多头信号：长周期RSI超卖且短周期RSI极度超卖
        if rsi_long > self.rsi_long_threshold and rsi_short > self.rsi_short_threshold:
            logger.info(f"RSI多头信号: rsi_long={rsi_long:.2f}, rsi_short={rsi_short:.2f}")
            return 1

        # 空头信号：长周期RSI超买且短周期RSI极度超买
        if rsi_long < (100 - self.rsi_long_threshold) and rsi_short < (
            100 - self.rsi_short_threshold
        ):
            logger.info(f"RSI空头信号: rsi_long={rsi_long:.2f}, rsi_short={rsi_short:.2f}")
            return -1

        return 0

    def _execute_signal(self, signal: int, bar: BarData):
        """
        执行交易信号

        Args:
            signal: 1=多头, -1=空头
            bar: 当前K线
        """
        # 检查是否使用信号
        if not self.used_signal:
            logger.debug(f"策略 [{self.strategy_id}] UsedSignal=False，跳过信号")
            return

        try:
            if signal == 1:
                # 开多仓
                order_id = self.buy(
                    symbol=f"{self.symbol}.{self.exchange}",
                    volume=self.volume_per_trade,
                    price=bar.close_price,
                    offset=Offset.OPEN,
                )
                if order_id:
                    self.holding = True
                    self.position_side = 1
                    self.entry_price = bar.close_price
                    self.entry_bar_time = bar.datetime
                    self.last_trade_date = self._get_trade_date(bar)
                    logger.info(f"开多仓: price={bar.close_price}, order_id={order_id}")

            elif signal == -1:
                # 开空仓
                order_id = self.sell(
                    symbol=f"{self.symbol}.{self.exchange}",
                    volume=self.volume_per_trade,
                    price=bar.close_price,
                    offset=Offset.OPEN,
                )
                if order_id:
                    self.holding = True
                    self.position_side = -1
                    self.entry_price = bar.close_price
                    self.entry_bar_time = bar.datetime
                    self.last_trade_date = self._get_trade_date(bar)
                    logger.info(f"开空仓: price={bar.close_price}, order_id={order_id}")

        except Exception as e:
            logger.error(f"执行交易信号失败: {e}", exc_info=True)

    def _check_exit_conditions(self, current_price: float) -> Optional[str]:
        """
        检查止盈止损条件

        Returns:
            Optional[str]: 止盈原因，None表示不触发
        """
        if not self.holding or self.entry_price <= 0:
            return None

        # 计算收益率
        ret = self.position_side * (current_price / self.entry_price - 1.0)

        # 止盈
        if ret >= self.take_profit_pct:
            logger.info(
                f"触发止盈: entry={self.entry_price}, current={current_price}, ret={ret:.4f}"
            )
            return "TAKE_PROFIT"

        # 止损
        if ret <= -self.stop_loss_pct:
            logger.info(
                f"触发止损: entry={self.entry_price}, current={current_price}, ret={ret:.4f}"
            )
            return "STOP_LOSS"

        return None

    def _close_position(self, reason: str):
        """平仓"""
        if not self.holding:
            return

        try:
            # 确定平仓方向
            if self.position_side == 1:
                # 平多仓
                order_id = self.sell(
                    symbol=f"{self.symbol}.{self.exchange}",
                    volume=self.volume_per_trade,
                    price=None,  # 市价平仓
                    offset=Offset.CLOSE,
                )
            else:
                # 平空仓
                order_id = self.buy(
                    symbol=f"{self.symbol}.{self.exchange}",
                    volume=self.volume_per_trade,
                    price=None,  # 市价平仓
                    offset=Offset.CLOSE,
                )

            if order_id:
                logger.info(
                    f"平仓成功: reason={reason}, side={self.position_side}, order_id={order_id}"
                )

            # 重置状态
            self.holding = False
            self.position_side = 0
            self.entry_price = 0.0
            self.entry_bar_time = None

        except Exception as e:
            logger.error(f"平仓失败: {e}", exc_info=True)

    def on_order(self, order):
        """订单状态回调"""
        logger.debug(f"策略 [{self.strategy_id}] 订单更新: {order.order_id} status={order.status}")

    def on_trade(self, trade):
        """成交回调"""
        logger.info(
            f"策略 [{self.strategy_id}] 成交: {trade.trade_id} {trade.symbol} "
            f"{trade.direction.value} {trade.volume} @{trade.price}"
        )


# 策略工厂函数，用于动态加载
def create_strategy(strategy_id: str, config: dict) -> RsiStrategy:
    """创建RSI策略实例"""
    return RsiStrategy(strategy_id, config)
