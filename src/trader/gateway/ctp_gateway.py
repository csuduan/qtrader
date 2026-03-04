"""
CTP Gateway 适配器（异步版本）

实现 BaseGateway 接口，支持 CTP 实盘交易。
需要安装 CTP SDK（如 openctp_ctp 或类似库）才能运行。

参考：
- CTP API 文档：https://www.simnow.com.cn
"""

import asyncio
import queue
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from src.app_context import get_app_context
from src.models.object import (
    AccountData,
    BarData,
    CancelRequest,
    ContractData,
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderRequest,
    OrderType,
    PositionData,
    ProductType,
    TickData,
    TradeData,
)
from src.trader.gateway.base_gateway import BaseGateway

# 从 ctp_api 导入 CTP API 封装类
from src.trader.gateway.ctp_api import CtpMdApi, CtpTdApi
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.bar_generator import MultiSymbolBarGenerator, parse_interval
from src.utils.config_loader import GatewayConfig
from src.utils.event import EventTypes
from src.utils.logger import get_logger

ctx = get_app_context()

logger = get_logger(__name__)


class CtpGateway(BaseGateway):
    """
    CTP Gateway 适配器（异步版本）

    实现 BaseGateway 接口，支持 CTP 实盘交易。
    """

    gateway_name = "CTP"

    def __init__(self, config: GatewayConfig):
        """初始化 CTP Gateway"""
        super().__init__()
        self.config = config
        self.account_id = config.account_id
        self.trading_day: Optional[str] = None
        self._running = False

        # 行情缓存（最新的 tick 数据）
        self._quotes: Dict[str, TickData] = {}

        # 成交缓存
        self._trades: Dict[str, TradeData] = {}

        # 账户数据缓存
        self._account: Optional[AccountData] = None

        # 持仓数据缓存
        self._positions: Dict[str, PositionData] = {}

        # 缓存报单数据
        self._orders: Dict[str, OrderData] = {}

        # K线订阅列表: [(symbol, interval), ...]
        self._bar_subs: List[Tuple[str, str]] = []

        # K线生成器（使用 utils.bar_generator）
        self._bar_generator = MultiSymbolBarGenerator()

        # 线程同步队列（线程安全）
        self._sync_queue: queue.Queue = queue.Queue(maxsize=5000)

        # 行情和交易接口
        self.md_api: Optional[CtpMdApi] = None
        self.td_api: Optional[CtpTdApi] = None

        # 事件分发协程
        self._dispatcher_task: Optional[asyncio.Task] = None

        # AsyncEventEngine引用（直接发送事件）
        self._event_engine: Optional[AsyncEventEngine] = ctx.get_event_engine()

        # 加载合约
        self.load_contracts()

        logger.info(f"CTP Gateway 初始化，账户: {self.account_id}")

    async def connect(self) -> bool:
        """连接到 CTP"""
        if self.connected:
            logger.warning("CTP Gateway 已连接")
            return True

        try:
            # 创建 API 实例
            self.md_api = CtpMdApi(self)
            self.td_api = CtpTdApi(self)

            # 连接行情和交易服务器
            self.md_api.connect()
            self.td_api.connect()

            self.connected = True
            logger.info("CTP Gateway 连接中...")

            self._running = True

            # 启动事件分发协程
            self._dispatcher_task = asyncio.create_task(self._event_dispatcher())
            return True

        except Exception as e:
            logger.exception(f"CTP Gateway 连接失败: {e}")
            return False

    async def disconnect(self) -> bool:
        """断开连接"""
        if self.md_api:
            self.md_api.close()
            self.md_api = None

        if self.td_api:
            self.td_api.close()
            self.td_api = None

        self.connected = False
        self._running = False
        logger.info("CTP Gateway 已断开")
        return True

    def send_order(self, req: OrderRequest) -> Optional[OrderData]:
        """下单"""
        if not self.td_api or not self.td_api.connected:
            logger.error("CTP 交易接口未连接")
            return None

        contract = self.contracts.get(req.symbol)
        if not contract:
            logger.warning(f"CTP 下单失败，未找到合约信息，合约: {req.symbol}")
            raise ValueError(f"未找到合约信息，合约: {req.symbol}")
        req.exchange = contract.exchange
        if not req.price or req.price <= 0:
            tick = self._quotes.get(req.symbol)
            if tick and tick.last_price is not None and tick.last_price > 0:
                req.price = tick.bid_price1 if req.direction == Direction.BUY else tick.ask_price1
            else:
                logger.warning(f"CTP 下单失败，未获取到有效价格，合约: {req.symbol}")
                raise ValueError(f"未获取到有效价格，合约: {req.symbol}")
        return self.td_api.insert_order(req)

    def cancel_order(self, req: CancelRequest) -> bool:
        """撤单"""
        if not self.td_api or not self.td_api.connected:
            return False

        return self.td_api.cancel_order(req)

    def get_trading_day(self) -> Optional[str]:
        """获取交易日"""
        return self.trading_day

    def get_account(self) -> Optional[AccountData]:
        """获取账户数据"""
        return self._account

    def get_positions(self) -> Dict[str, PositionData]:
        """获取持仓数据"""
        return self._positions.copy()

    def get_orders(self) -> Dict[str, OrderData]:
        """获取订单数据"""
        return self._orders.copy()

    def get_trades(self) -> Dict[str, TradeData]:
        """获取成交数据"""
        return self._trades.copy()

    def get_contracts(self) -> Dict[str, ContractData]:
        """获取所有合约信息"""
        return self.contracts.copy()

    def get_quotes(self) -> Dict[str, TickData]:
        """获取行情数据"""
        return self._quotes.copy()

    def get_kline(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """
        获取K线数据

        Args:
            symbol: 合约代码
            interval: 周期（如"M1", "M5", "M15", "H1"等）

        Returns:
            Optional[pd.DataFrame]: K线数据框，失败返回None
        """
        std_symbol = self.std_symbol(symbol) or symbol

        # 从 BarGenerator 获取已完成的K线
        generator = self._bar_generator.get(std_symbol)
        if not generator:
            return None

        bars = generator.get_bars(interval, count=500)
        if not bars:
            return None

        # 转换为 DataFrame
        data = []
        for bar in bars:
            data.append(
                {
                    "datetime": bar.datetime,
                    "open": bar.open_price,
                    "high": bar.high_price,
                    "low": bar.low_price,
                    "close": bar.close_price,
                    "volume": bar.volume or 0,
                    "turnover": bar.turnover or 0,
                    "open_interest": bar.open_interest or 0,
                }
            )

        df = pd.DataFrame(data)
        return df

    def subscribe(self, symbol: Union[str, List[str]]) -> bool:
        """订阅行情"""
        if isinstance(symbol, str):
            symbol = [symbol]
        if self.md_api is None:
            logger.error("CTP 行情接口未连接")
            return False
        self.md_api.subscribe(symbol)  # type: ignore[arg-type]
        return True

    def subscribe_bars(self, symbol: str, interval: str) -> bool:
        """
        订阅K线数据

        CTP 不直接提供K线数据，需要基于tick合成。

        Args:
            symbol: 合约代码
            interval: 周期（如"M1", "M5", "M15", "H1"等）

        Returns:
            bool: 订阅是否成功
        """
        std_symbol = self.std_symbol(symbol) or symbol
        key = (std_symbol, interval)

        if key in self._bar_subs:
            return True

        # 验证时间间隔格式
        if not parse_interval(interval):
            logger.error(f"不支持的K线周期: {interval}")
            return False

        # 添加到订阅列表
        self._bar_subs.append(key)

        # 获取或创建 BarGenerator 并订阅周期
        bar_gen = self._bar_generator.get_or_create(std_symbol)

        # 注册回调函数
        def on_bar_complete(bar: BarData) -> None:
            """K线完成回调"""
            self._push_bar(bar)

        bar_gen.subscribe(interval, on_bar_complete)

        logger.info(f"订阅K线数据: {std_symbol} {interval}")
        return True

    def get_contract(self, symbol: str) -> Optional[ContractData]:
        """获取合约信息"""
        return self.contracts.get(symbol)

    async def _event_dispatcher(self):
        """
        事件分发协程（在主线程事件循环中运行）

        职责：
        1. 从同步队列获取数据
        2. 直接推送到AsyncEventEngine
        """
        try:
            logger.info("事件分发协程已启动")
            while self._running:
                try:
                    # 从同步队列获取数据（超时1秒）
                    if self._sync_queue.empty():
                        await asyncio.sleep(0)
                        continue
                    event_type, data = await asyncio.to_thread(self._sync_queue.get, timeout=1.0)
                    if self._event_engine:
                        self._event_engine.put(event_type, data)

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.exception(f"事件分发异常: {e}")

            logger.info("事件分发协程已退出")

        except asyncio.CancelledError:
            logger.info("事件分发协程已取消")
        except Exception as e:
            logger.exception(f"事件分发协程致命错误: {e}")

    def add_trade(self, trade: TradeData) -> None:
        """添加成交"""
        self._trades[trade.trade_id] = trade

    def add_position(self, position: PositionData) -> None:
        """添加持仓"""
        self._positions[position.symbol] = position

    def add_order(self, order: OrderData) -> None:
        """添加订单"""
        self._orders[order.order_id] = order

    def add_contract(self, contract: ContractData) -> None:
        """添加合约"""
        self.contracts[contract.symbol] = contract

    # ==================== 处理ctp_api回调 ====================
    def on_tick(self, tick: TickData) -> None:
        """处理 tick 回调"""
        # 缓存行情数据
        self._quotes[tick.symbol] = tick
        self._push_to_queue(EventTypes.TICK_UPDATE, tick)

        # 推送 tick 给 BarGenerator 合成 K 线
        self._bar_generator.update_tick(tick)

        # 刷新持仓盈亏
        self._update_hold_profit(tick)

    def on_order(self, order: OrderData) -> None:
        """处理订单回调"""
        # 缓存订单数据
        self.add_order(order)
        self._push_to_queue(EventTypes.ORDER_UPDATE, order)
        logger.info(f"报单回报: {order}")

    def on_trade(self, trade: TradeData) -> None:
        """处理成交回调"""
        # 缓存成交数据
        self.add_trade(trade)
        self._push_to_queue(EventTypes.TRADE_UPDATE, trade)
        logger.info(f"成交回报: {trade}")

        # 更新持仓
        self._update_position(trade)

    def _update_position(self, trade: TradeData) -> None:
        """根据成交更新持仓"""
        symbol = trade.symbol
        volume = trade.volume
        price = trade.price

        # 获取或创建持仓
        position = self._positions.get(symbol)
        if not position:
            # 获取合约乘数
            contract = self.contracts.get(symbol)
            multiple = contract.multiple if contract and contract.multiple else 1

            position = PositionData.model_construct(
                account_id=self.account_id,
                symbol=symbol,
                exchange=trade.exchange,
                multiple=multiple,
                pos=0,
                pos_long=0,
                pos_short=0,
                pos_long_yd=0,
                pos_short_yd=0,
                pos_long_td=0,
                pos_short_td=0,
                open_price_long=0.0,
                open_price_short=0.0,
                hold_price_long=0.0,
                hold_price_short=0.0,
                hold_cost_long=0.0,
                hold_cost_short=0.0,
                float_profit_long=0.0,
                float_profit_short=0.0,
                hold_profit_long=0.0,
                hold_profit_short=0.0,
                margin_long=0.0,
                margin_short=0.0,
            )
            self._positions[symbol] = position

        # 根据买卖方向和开平标志更新持仓
        is_open = trade.offset == Offset.OPEN
        is_buy = trade.direction == Direction.BUY

        # 确保 hold_cost 不为 None
        hold_cost_long = position.hold_cost_long or 0.0
        hold_cost_short = position.hold_cost_short or 0.0

        if is_open:
            # 开仓：增加持仓
            if is_buy:
                # 开多
                position.hold_cost_long = (
                    hold_cost_long * position.pos_long + price * volume * position.multiple
                )
                position.pos_long += volume
                position.hold_cost_long = position.hold_cost_long if position.pos_long > 0 else 0.0
                position.hold_price_long = (
                    round(position.hold_cost_long / position.pos_long / position.multiple, 2)
                    if position.pos_long > 0
                    else 0.0
                )
                # 开仓全部算今仓
                position.pos_long_td = (position.pos_long_td or 0) + volume
            else:
                # 开空
                position.hold_cost_short = (
                    hold_cost_short * position.pos_short + price * volume * position.multiple
                )
                position.pos_short += volume
                position.hold_cost_short = (
                    position.hold_cost_short if position.pos_short > 0 else 0.0
                )
                position.hold_price_short = (
                    round(position.hold_cost_short / position.pos_short / position.multiple, 2)
                    if position.pos_short > 0
                    else 0.0
                )
                # 开仓全部算今仓
                position.pos_short_td = (position.pos_short_td or 0) + volume
        else:
            # 平仓：减少持仓
            if is_buy:
                # 平空（买入平空）
                if position.pos_short > 0:
                    # 按比例减少持仓成本
                    hold_cost_short = position.hold_cost_short or 0.0
                    if position.pos_short > volume:
                        position.hold_cost_short = (
                            hold_cost_short * (position.pos_short - volume) / position.pos_short
                        )
                    else:
                        position.hold_cost_short = 0.0
                    position.pos_short = max(0, position.pos_short - volume)

                    # 处理今仓/昨仓
                    pos_short_td = position.pos_short_td or 0
                    pos_short_yd = position.pos_short_yd or 0
                    if trade.offset == Offset.CLOSETODAY:
                        # 平今仓
                        position.pos_short_td = max(0, pos_short_td - volume)
                    else:
                        # 平昨仓（优先减昨仓）
                        yd_to_close = min(pos_short_yd, volume)
                        position.pos_short_yd = max(0, pos_short_yd - yd_to_close)
                        remaining = volume - yd_to_close
                        if remaining > 0:
                            position.pos_short_td = max(0, pos_short_td - remaining)

                    # 更新持仓均价
                    hold_cost_short_new = position.hold_cost_short or 0.0
                    position.hold_price_short = (
                        round(hold_cost_short_new / position.pos_short / position.multiple, 2)
                        if position.pos_short > 0
                        else 0.0
                    )
            else:
                # 平多（卖出平多）
                if position.pos_long > 0:
                    # 按比例减少持仓成本
                    hold_cost_long = position.hold_cost_long or 0.0
                    if position.pos_long > volume:
                        position.hold_cost_long = (
                            hold_cost_long * (position.pos_long - volume) / position.pos_long
                        )
                    else:
                        position.hold_cost_long = 0.0
                    position.pos_long = max(0, position.pos_long - volume)

                    # 处理今仓/昨仓
                    pos_long_td = position.pos_long_td or 0
                    pos_long_yd = position.pos_long_yd or 0
                    if trade.offset == Offset.CLOSETODAY:
                        # 平今仓
                        position.pos_long_td = max(0, pos_long_td - volume)
                    else:
                        # 平昨仓（优先减昨仓）
                        yd_to_close = min(pos_long_yd, volume)
                        position.pos_long_yd = max(0, pos_long_yd - yd_to_close)
                        remaining = volume - yd_to_close
                        if remaining > 0:
                            position.pos_long_td = max(0, pos_long_td - remaining)

                    # 更新持仓均价
                    hold_cost_long_new = position.hold_cost_long or 0.0
                    position.hold_price_long = (
                        round(hold_cost_long_new / position.pos_long / position.multiple, 2)
                        if position.pos_long > 0
                        else 0.0
                    )

        # 更新净持仓
        position.pos = position.pos_long - position.pos_short

        # 平仓时更新账户平仓盈亏
        if not is_open:
            self._update_close_profit(trade, position, volume)

        # 推送更新后的持仓
        self._push_to_queue(EventTypes.POSITION_UPDATE, position)

    def on_account(self, account: AccountData) -> None:
        """处理账户回调"""
        # 缓存账户数据
        self._account = account
        self._push_to_queue(EventTypes.ACCOUNT_UPDATE, account)

    def on_status(self) -> None:
        """处理状态回调"""
        if self.td_api is None or self.md_api is None:
            return
        self.connected = self.td_api.is_ready and self.md_api.connected
        if self.connected:
            # 订阅行情
            self.md_api.resubscribe()
            # 订阅k线
            for sub_bar in self.config.subscribe_bars:
                symbol, interval = sub_bar.split("-")
                self.subscribe_bars(symbol, interval)

    def _push_to_queue(self, event_type: str, data: Any):
        """推送数据到同步队列（非阻塞）"""
        try:
            self._sync_queue.put_nowait((event_type, data))
        except queue.Full:
            logger.warning(f"事件队列已满，丢弃事件: {event_type}")

    def _update_close_profit(self, trade: TradeData, position: PositionData, volume: int) -> None:
        """
        更新账户当日平仓盈亏

        Args:
            trade: 成交数据
            position: 持仓数据
            volume: 平仓手数
        """
        if not self._account:
            return

        multiple = position.multiple
        trade_price = trade.price
        close_profit_long = position.close_profit_long or 0.0
        close_profit_short = position.close_profit_short or 0.0

        # 计算平仓盈亏
        if trade.direction == Direction.SELL:
            # 平多：(平仓价 - 持仓价) × 手数 × 乘数
            hold_price = position.hold_price_long or trade_price
            profit = (trade_price - hold_price) * volume * multiple
            position.close_profit_long = close_profit_long + profit
        else:
            # 平空：(持仓价 - 平仓价) × 手数 × 乘数
            hold_price = position.hold_price_short or trade_price
            profit = (hold_price - trade_price) * volume * multiple
            position.close_profit_short = close_profit_short + profit

        # 累加当日平仓盈亏
        if self._account.close_profit is None:
            self._account.close_profit = 0.0
        self._account.close_profit += profit

    def _update_hold_profit(self, tick: TickData) -> None:
        """
        根据最新行情更新持仓盈亏和最新价

        Args:
            tick: 最新tick数据
        """
        symbol = tick.symbol
        position = self._positions.get(symbol)
        if not position or tick.last_price is None or tick.last_price <= 0:
            return

        multiple = position.multiple
        last_price = tick.last_price
        hold_price_long = position.hold_price_long or 0.0
        hold_price_short = position.hold_price_short or 0.0

        # 更新最新价
        position.last_price = last_price

        # 更新多头浮动盈亏
        if position.pos_long > 0:
            position.hold_profit_long = (
                (last_price - hold_price_long) * position.pos_long * multiple
            )

        # 更新空头浮动盈亏
        if position.pos_short > 0:
            position.hold_profit_short = (
                (hold_price_short - last_price) * position.pos_short * multiple
            )

        # 更新账户持仓盈亏
        if self._account:
            total_hold_profit = (position.hold_profit_long or 0) + (position.hold_profit_short or 0)
            self._account.hold_profit = total_hold_profit

    def _push_bar(self, bar_data: BarData) -> None:
        """
        推送K线数据到事件队列

        Args:
            bar_data: K线数据
        """
        self._push_to_queue(EventTypes.KLINE_UPDATE, bar_data)
        logger.info(f"推送K线: {bar_data}")
