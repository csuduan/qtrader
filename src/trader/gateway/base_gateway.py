"""
Gateway适配器基类
定义统一的接口契约，具体Gateway实现继承此类
"""

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

import pandas as pd

from src.models.object import (
    AccountData,
    BarData,
    CancelRequest,
    ContractData,
    OrderData,
    OrderRequest,
    OrderStatus,
    PositionData,
    SubscribeRequest,
    TickData,
    TradeData,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 支持异步和同步回调
AsyncTickCallback = Callable[[TickData], None] | Callable[[TickData], Awaitable[None]]
AsyncBarCallback = Callable[[BarData], None] | Callable[[BarData], Awaitable[None]]
AsyncOrderCallback = Callable[[OrderData], None] | Callable[[OrderData], Awaitable[None]]
AsyncTradeCallback = Callable[[TradeData], None] | Callable[[TradeData], Awaitable[None]]
AsyncPositionCallback = Callable[[PositionData], None] | Callable[[PositionData], Awaitable[None]]
AsyncAccountCallback = Callable[[AccountData], None] | Callable[[AccountData], Awaitable[None]]
AsyncContractCallback = Callable[[ContractData], None] | Callable[[ContractData], Awaitable[None]]


class BaseGateway(ABC):
    """
    Gateway抽象基类（异步版本）

    职责：
    1. 连接/断开交易接口
    2. 订阅/取消订阅行情
    3. 下单/撤单
    4. 数据格式转换（Gateway特定格式 → 统一模型）
    5. 通过回调向上层推送数据

    设计原则：
    - 不处理业务逻辑（如风控、策略）
    - 不保存状态（状态由上层AccountManager管理）
    - 不直接访问数据库
    - 所有公共接口改为异步
    """

    # Gateway名称
    gateway_name: str = "BaseGateway"

    # 支持的交易所列表
    exchanges: list = []

    def __init__(self):
        """初始化Gateway"""
        self.connected: bool = False
        self.trading_day: Optional[str] = None

        # 回调函数（由上层注册，支持异步）
        self.on_tick_callback: Optional[AsyncTickCallback] = None
        self.on_bar_callback: Optional[AsyncBarCallback] = None
        self.on_order_callback: Optional[AsyncOrderCallback] = None
        self.on_trade_callback: Optional[AsyncTradeCallback] = None
        self.on_position_callback: Optional[AsyncPositionCallback] = None
        self.on_account_callback: Optional[AsyncAccountCallback] = None
        self.on_contract_callback: Optional[AsyncContractCallback] = None

        # 策略专用回调
        self.on_tick_strategy: Optional[AsyncTickCallback] = None
        self.on_bar_strategy: Optional[AsyncBarCallback] = None

        logger.info(f"{self.gateway_name} Gateway 初始化完成")

    # ==================== 回调注册 ====================

    def register_callbacks(self, **callbacks):
        """
        注册回调函数

        Args:
            on_tick: tick行情回调（支持异步）
            on_bar: bar行情回调（支持异步）
            on_order: 订单状态回调（支持异步）
            on_trade: 成交回调（支持异步）
            on_position: 持仓回调（支持异步）
            on_account: 账户回调（支持异步）
            on_contract: 合约回调（支持异步）
        """
        self.on_tick_callback = callbacks.get("on_tick")
        self.on_bar_callback = callbacks.get("on_bar")
        self.on_order_callback = callbacks.get("on_order")
        self.on_trade_callback = callbacks.get("on_trade")
        self.on_position_callback = callbacks.get("on_position")
        self.on_account_callback = callbacks.get("on_account")
        self.on_contract_callback = callbacks.get("on_contract")

        logger.info(f"{self.gateway_name} 回调注册完成")

    def register_strategy_callbacks(
        self, on_tick: AsyncTickCallback, on_bar: AsyncBarCallback
    ):
        """注册策略专用回调"""
        self.on_tick_strategy = on_tick
        self.on_bar_strategy = on_bar
        logger.info(f"{self.gateway_name} 策略回调注册完成")

    # ==================== 连接管理 ====================

    @abstractmethod
    async def connect(self) -> bool:
        """
        连接到交易接口

        Returns:
            bool: 连接是否成功
        """
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """
        断开交易接口连接

        Returns:
            bool: 断开是否成功
        """
        pass

    @abstractmethod
    def get_trading_day(self) -> Optional[str]:
        """
        获取当前交易日

        Returns:
            Optional[str]: 交易日日期（YYYYMMDD）
        """
        pass

    # ==================== 行情订阅 ====================

    @abstractmethod
    def subscribe(self, symbol: Union[str, List[str]]) -> bool:
        """
        订阅行情（异步）

        Args:
            symbol: 订阅合约

        Returns:
            bool: 订阅是否成功
        """
        pass

    @abstractmethod
    def subscribe_bars(self, symbol: str, interval: str) -> bool:
        """
        订阅K线数据

        Args:
            symbol: 订阅合约
            interval: K线时间间隔

        Returns:
            bool: 订阅是否成功
        """
        pass

    # ==================== 交易接口 ====================

    @abstractmethod
    def send_order(self, req: OrderRequest) -> Optional[OrderData]:
        """
        下单（异步）

        Args:
            req: 下单请求

        Returns:
            Optional[OrderData]: 报单信息，失败返回None
        """
        pass

    @abstractmethod
    def cancel_order(self, req: CancelRequest) -> bool:
        """
        撤单

        Args:
            req: 撤单请求

        Returns:
            bool: 撤单是否成功
        """
        pass

    # ==================== 查询接口 ====================

    @abstractmethod
    def get_account(self) -> Optional[AccountData]:
        """
        查询账户信息

        Returns:
            Optional[AccountData]: 账户数据
        """
        pass

    @abstractmethod
    def get_positions(self) -> dict[str, PositionData]:
        """
        查询持仓信息

        Returns:
            dict[str,PositionData]: 持仓列表
        """
        pass

    @abstractmethod
    def get_orders(self) -> dict[str, OrderData]:
        """
        查询活动订单

        Returns:
            dict[str,OrderData]: 订单列表
        """
        pass

    @abstractmethod
    def get_trades(self) -> dict[str, TradeData]:
        """
        查询今日成交

        Returns:
            dict[str,TradeData]: 成交列表
        """
        pass

    @abstractmethod
    def get_contracts(self) -> Dict[str, ContractData]:
        """
        查询所有合约信息

        Returns:
            Dict[str, ContractData]: 合约字典 {symbol: ContractData}
        """

    @abstractmethod
    def get_quotes(self) -> dict[str, TickData]:
        """
        查询所有合约行情

        Returns:
            dict[str, QuoteData]: 行情字典 {symbol: QuoteData}
        """
        pass

    @abstractmethod
    def get_kline(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """
        获取K线数据

        Args:
            symbol: 合约代码
            interval: 周期（如"M1"）

        Returns:
            Optional[pd.DataFrame]: K线数据框，失败返回None
        """
        pass
