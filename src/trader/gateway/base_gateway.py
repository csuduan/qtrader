"""
Gateway适配器基类
定义统一的接口契约，具体Gateway实现继承此类
"""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Dict, Optional, Union

import pandas as pd

from src.models.object import (
    AccountData,
    CancelRequest,
    ContractData,
    Exchange,
    Interval,
    OrderData,
    OrderRequest,
    PositionData,
    ProductType,
    TickData,
    TradeData,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BaseGateway(ABC):
    """
    Gateway抽象基类

    职责：
    1. 连接/断开交易接口
    2. 订阅/取消订阅行情
    3. 下单/撤单
    4. 数据格式转换（Gateway特定格式 → 统一模型）

    设计原则：
    - 不处理业务逻辑（如风控、策略）
    - 不保存状态（状态由上层AccountManager管理）
    - 不直接访问数据库
    - 所有公共接口改为异步
    """

    # Gateway名称
    gateway_name: str = "BaseGateway"

    def __init__(self):
        """初始化Gateway"""
        self.connected: bool = False
        self.trading_day: Optional[str] = None
        self.contracts: Dict[str, ContractData] = {}
        self.positions: Dict[str, PositionData] = {}
        # 合约更新日期，用于判断是否需要重新查询
        self._contracts_update_date: Optional[str] = None
        logger.info(f"{self.gateway_name} Gateway 初始化完成")

    def std_symbol(self, symbol: str) -> Optional[str]:
        """
        标准化合约代码
        将各种格式的合约代码转换为统一格式 "symbol"

        Args:
            symbol: 合约代码，支持以下格式：
                - "SHFE.rb2505" (exchange.symbol)
                - "rb2505.SHFE" (symbol.exchange)
                - "rb2505" 或 "RB2505" (仅合约代码)

        Returns:
            标准化后的合约代码 "rb2505"，找不到时返回 None
        """
        if not symbol:
            return None

        symbol = symbol.strip()

        # 已经是标准格式 "symbol.exchange"
        if "." in symbol:
            parts = symbol.split(".")
            if len(parts) != 2:
                logger.warning(f"无法识别交易所: {symbol}")
                return None
            first, second = parts
            std_symbol = None
            exchange = None
            # 判断哪个是交易所
            if first.upper() in Exchange.__members__:
                # 格式: "SHFE.rb2505" -> "rb2505.SHFE"
                std_symbol = second
                exchange = first.upper()
            elif second.upper() in Exchange.__members__:
                # 格式: "rb2505.SHFE" -> 保持不变
                std_symbol = first
                exchange = second.upper()
            else:
                # 无法识别交易所，尝试从合约缓存中查找
                logger.warning(f"无法识别交易所: {symbol}")
                return None
            if exchange in ["CZCE", "CFFEX"]:
                std_symbol = std_symbol.upper()
            else:
                std_symbol = std_symbol.lower()
            return std_symbol
        else:
            # 尝试从合约缓存中查找
            symbol_lower = symbol.lower()
            symbol_upper = symbol.upper()
            # 直接匹配
            contract = self.contracts.get(symbol_upper) or self.contracts.get(symbol_lower)
            if not contract:
                return symbol
            return contract.symbol

    def load_contracts(self) -> Optional[dict[str, ContractData]]:
        """
        从数据库加载指定更新日期的合约信息

        Args:
            update_date: 更新日期 (YYYY-MM-DD)
        Returns:
            合约信息字典，如果没有则返回None
        """
        from src.models.po import ContractPo
        from src.utils.database import session_scope

        update_date = datetime.now().strftime("%Y-%m-%d")
        try:
            with session_scope() as session:
                contract_pos = (
                    session.query(ContractPo).filter(ContractPo.update_date == update_date).all()
                )

                if not contract_pos:
                    logger.info(f"数据库中没有更新日期为 {update_date} 的合约信息")
                    return None

                loaded_count = 0
                for po in contract_pos:
                    symbol = po.symbol.split(".")[1] if "." in po.symbol else po.symbol  # type: ignore[union-attr]
                    exchange = Exchange.from_str(po.exchange_id)  # type: ignore[arg-type]
                    if exchange == Exchange.NONE:
                        continue
                    contract = ContractData(
                        symbol=symbol,  # type: ignore[arg-type]
                        exchange=exchange,
                        name=po.instrument_name or po.symbol,  # type: ignore[arg-type]
                        product_type=ProductType.FUTURES,
                        multiple=po.volume_multiple,  # type: ignore[arg-type]
                        pricetick=float(po.price_tick),
                        min_volume=po.min_volume,  # type: ignore[arg-type]
                        option_strike=float(po.option_strike) if po.option_strike else None,
                        option_underlying=po.option_underlying,  # type: ignore[arg-type]
                        option_type=po.option_type,  # type: ignore[arg-type]
                    )  # type: ignore[call-arg]
                    self.contracts[contract.symbol] = contract
                    # self._upper_symbols[contract.symbol.rsplit(".")[1].upper()] = contract.exchange.value
                    loaded_count += 1

                # 记录合约更新日期
                self._contracts_update_date = update_date
                logger.info(f"从数据库加载了 {loaded_count} 个合约信息 (更新日期: {update_date})")
                return self.contracts
        except Exception as e:
            logger.error(f"从数据库加载合约信息失败: {e}")
            return None

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

    @abstractmethod
    def subscribe(self, symbols: list[str]) -> bool:
        """
        订阅行情

        Args:
            symbols: 订阅合约列表

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

    @abstractmethod
    def send_order(self, req: OrderRequest) -> Optional[OrderData]:
        """
        下单

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
    def get_contracts(self) -> dict[str, ContractData]:
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
