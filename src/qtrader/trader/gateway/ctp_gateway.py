"""
CTP Gateway 适配器（异步版本）

实现 BaseGateway 接口，支持 CTP 实盘交易。

参考：
- CTP API 文档：https://www.simnow.com.cn
"""

import queue
from typing import Any

import pandas as pd

from qtrader.app_context import get_app_context
from qtrader.models.object import (
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
from qtrader.trader.gateway.base_gateway import BaseGateway

# 从 ctp_api 导入 CTP API 封装类
from qtrader.trader.gateway.ctp_api import CtpMdApi, CtpTdApi
from qtrader.utils.bar_generator import MultiSymbolBarGenerator, parse_interval
from qtrader.utils.config_loader import GatewayConfig, TraderConfig
from qtrader.utils.event import EventTypes
from qtrader.utils.logger import get_logger

ctx = get_app_context()

logger = get_logger(__name__)


class CtpGateway(BaseGateway):
    """
    CTP Gateway 适配器（异步版本）

    实现 BaseGateway 接口，支持 CTP 实盘交易。
    """

    gateway_name = "CTP"

    def __init__(self, acct_config: TraderConfig):
        """初始化 CTP Gateway"""
        super().__init__()
        self.config = acct_config.gateway
        self.account_id = acct_config.account_id
        self.trading_day: str | None = None
        self._running = False

        # 行情缓存（最新的 tick 数据）
        self._quotes: dict[str, TickData] = {}

        # 成交缓存
        self._trades: dict[str, TradeData] = {}

        # 账户数据缓存
        self._account: AccountData | None = None

        # 持仓数据缓存
        self._positions: dict[str, PositionData] = {}

        # 缓存报单数据
        self._orders: dict[str, OrderData] = {}

        # K线订阅列表: [(symbol, interval), ...]
        self._bar_subs: list[tuple[str, str]] = []
        # 订阅合约列表
        self._sub_symbols: set[str] = set()

        # K线生成器（使用 utils.bar_generator）
        self._bar_generator = MultiSymbolBarGenerator()

        # 行情和交易接口
        self.md_api: CtpMdApi | None = None
        self.td_api: CtpTdApi | None = None

        # 订阅配置（来自全局config.yaml）
        self.subs_config = acct_config.subs

        # 加载合约
        self.load_contracts()

        logger.info(f"CTP Gateway 初始化，账户: {self.account_id}")

    async def connect(self) -> bool:
        """连接到 CTP"""
        if self.connected:
            logger.warning("CTP Gateway 已连接")
            return True

        if self._running:
            logger.warning("CTP Gateway 运行中，先断开连接")
            await self.disconnect()

        self._running = True
        try:
            # 清空历史数据
            self._positions.clear()
            self._trades.clear()
            self._orders.clear()

            # 创建 API 实例
            self.md_api = CtpMdApi(self)
            self.td_api = CtpTdApi(self)

            # 连接行情和交易服务器
            self.md_api.connect()
            self.td_api.connect()
            logger.info("CTP Gateway 连接中...")

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

        self.md_connected = False
        self.td_connected = False
        self._running = False
        if self._account:
            self._account.td_connected = False
            self._account.md_connected = False
            self.emit_event(EventTypes.ACCOUNT_UPDATE, self._account)
        logger.info("CTP Gateway 已断开")
        return True

    def send_order(self, req: OrderRequest) -> OrderData | None:
        """下单"""
        if not self.td_connected:
            logger.error("CTP 交易接口未连接")
            return None

        contract = self.contracts.get(req.symbol)
        if not contract:
            logger.warning(f"CTP 下单失败，未找到合约信息，合约: {req.symbol}")
            raise ValueError(f"未找到合约信息，合约: {req.symbol}")
        req.exchange = contract.exchange
        tick_price: float = 0.0
        if req.slip is not None and req.slip > 0 and contract.pricetick is not None:
            tick_price = contract.pricetick * req.slip

        if not req.price or req.price <= 0:
            tick = self._quotes.get(req.symbol)
            if tick and tick.last_price is not None and tick.last_price > 0:
                req.price = (
                    (tick.bid_price1 or 0) + tick_price
                    if req.direction == Direction.BUY
                    else (tick.ask_price1 or 0) - tick_price
                )
            else:
                logger.warning(f"CTP 下单失败，未获取到有效价格，合约: {req.symbol}")
                raise ValueError(f"未获取到有效价格，合约: {req.symbol}")
        if self.td_api is None:
            raise ValueError("CTP 交易接口未初始化")
        return self.td_api.insert_order(req)

    def cancel_order(self, req: CancelRequest) -> bool:
        """撤单"""
        if not self.td_api or not self.td_api.connected:
            return False

        return self.td_api.cancel_order(req)

    def get_trading_day(self) -> str | None:
        """获取交易日"""
        return self.trading_day

    def get_account(self) -> AccountData | None:
        """获取账户数据"""
        if self._account:
            self._account.hold_profit = sum(
                position.hold_profit for position in self._positions.values()
            )
            self._account.close_profit = sum(
                position.close_profit for position in self._positions.values()
            )
            self._account.balance = (
                (self._account.static_balance or 0)
                + self._account.hold_profit
                + self._account.close_profit
            )
            self._account.td_connected = self.td_connected
            self._account.md_connected = self.md_connected
            return self._account

        broker = self.config.broker if self.config else None
        default_account = AccountData(
            account_id=self.account_id,
            currency="CNY",
            balance=0.0,
            frozen_balance=0.0,
            available=0.0,
            md_connected=self.md_connected,
            td_connected=self.td_connected,
            user_id=(broker.user_id if broker else None) or "--",
            broker_name=(broker.broker_name if broker else None) or "--",
            broker_type=(broker.type if broker else None) or "--",
        )
        return default_account

    def get_positions(self) -> dict[str, PositionData]:
        """获取持仓数据"""
        return self._positions.copy()

    def get_orders(self) -> dict[str, OrderData]:
        """获取订单数据"""
        return self._orders.copy()

    def get_trades(self) -> dict[str, TradeData]:
        """获取成交数据"""
        return self._trades.copy()

    def get_contracts(self) -> dict[str, ContractData]:
        """获取所有合约信息"""
        return self.contracts.copy()

    def refresh_contracts(self) -> bool:
        """
        强制刷新合约信息，从API重新查询并更新数据库

        Returns:
            bool: 刷新是否成功
        """
        try:
            if not self.connected or not self.td_api:
                logger.error("CTP未连接，无法刷新合约信息")
                return False

            logger.info("开始强制刷新CTP合约信息")

            # 先获取查询信号量（查询串行化，避免与查询线程并发触发CTP流控；
            # query_instrument 内部在失败早退/回报完成时释放）
            acquired = self.td_api.semaphore.acquire(timeout=5)
            if not acquired:
                logger.error("强制刷新CTP合约信息失败：查询信号量获取超时")
                return False

            # 调用API查询合约（force=True 跳过缓存判断）
            self.td_api.query_instrument(force=True)

            logger.info(f"强制刷新CTP合约信息请求已发送")
            return True
        except Exception as e:
            logger.exception(f"强制刷新CTP合约信息失败: {e}")
            return False

    def get_quotes(self) -> dict[str, TickData]:
        """获取行情数据"""
        return self._quotes.copy()

    def get_kline(self, symbol: str, interval: str) -> pd.DataFrame | None:
        """
        获取K线数据

        Args:
            symbol: 合约代码
            interval: 周期（如"M1", "M5", "M15", "H1"等）

        Returns:
            pd.DataFrame | None: K线数据框，失败返回None
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

    def subscribe(self, symbol: str | list[str]) -> bool:
        """订阅行情"""
        if isinstance(symbol, str):
            symbol = [symbol]
        if self.md_api is None or not self.md_connected:
            logger.warning("CTP 行情接口未连接，延迟订阅")
            self._sub_symbols.update(symbol)
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

    def get_contract(self, symbol: str) -> ContractData | None:
        """获取合约信息"""
        return self.contracts.get(symbol)

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
        self.emit_event(EventTypes.TICK_UPDATE, tick)

        # 推送 tick 给 BarGenerator 合成 K 线
        self._bar_generator.update_tick(tick)

        # 刷新持仓盈亏
        position = self._positions.get(tick.symbol)
        if position:
            position.update_position(tick)

    def on_order(self, order: OrderData) -> None:
        """处理订单回调"""
        # 缓存订单数据
        self.add_order(order)
        self.emit_event(EventTypes.ORDER_UPDATE, order)
        logger.info(f"报单回报: {order}")

    def on_trade(self, trade: TradeData) -> None:
        """处理成交回调"""
        # 从订单缓存中获取报单价格（用于计算滑点）
        order = self._orders.get(trade.order_id)
        if order:
            trade.order_price = order.price

        # 缓存成交数据
        self.add_trade(trade)
        self.emit_event(EventTypes.TRADE_UPDATE, trade)
        logger.info(f"成交回报: {trade}")

        # 更新持仓
        symbol = trade.symbol
        position = self._positions.get(symbol)
        if not position:
            # 获取合约乘数
            contract = self.contracts.get(symbol)
            multiple = contract.multiple if contract and contract.multiple else 1
            position = PositionData.default(symbol, trade.exchange, multiple)
            self._positions[symbol] = position
        position.update_position(trade)
        # 推送更新后的持仓（标记为交易来源）
        position_data = position.model_dump()
        position_data["_source"] = "trade"  # 标记来源为交易
        self.emit_event(EventTypes.POSITION_UPDATE, position_data)

    def on_account(self, account: AccountData) -> None:
        """处理账户回调"""
        # 缓存账户数据
        self._account = account
        self._account.hold_profit = sum(
            (position.hold_profit_long or 0) + (position.hold_profit_short or 0)
            for position in self._positions.values()
        )
        self._account.close_profit = sum(
            (position.close_profit_long or 0) + (position.close_profit_short or 0)
            for position in self._positions.values()
        )
        self.emit_event(EventTypes.ACCOUNT_UPDATE, self._account)

    def on_status(self, ready: bool = False) -> None:
        """处理状态回调"""
        if self.td_api is None or self.md_api is None:
            return
        self.md_connected = self.md_api.connected
        self.td_connected = self.td_api.connected

        # 推送最新账户信息，确保前端连接状态实时更新
        account = self.get_account()
        if account:
            account.md_connected = self.md_connected
            account.td_connected = self.td_connected
            self.emit_event(EventTypes.ACCOUNT_UPDATE, account)

            if ready:
                self.emit_event(EventTypes.ACCOUNT_READY, None)

        if self.connected:
            # 订阅行情
            self.md_api.subscribe(sorted(self._sub_symbols))
            self.md_api.subscribe(self.subs_config.subscribe_symbols)

            # 订阅持仓
            if len(self._positions) > 0:
                self.subscribe([pos.symbol for pos in self._positions.values()])
            # 订阅k线（从全局配置加载）
            for sub_bar in self.subs_config.subscribe_bars:
                symbol, interval = sub_bar.split("-")
                self.subscribe_bars(symbol, interval)

    def _push_bar(self, bar_data: BarData) -> None:
        """
        推送K线数据到事件队列

        Args:
            bar_data: K线数据
        """
        self.emit_event(EventTypes.KLINE_UPDATE, bar_data)
        logger.info(f"推送K线: {bar_data}")
