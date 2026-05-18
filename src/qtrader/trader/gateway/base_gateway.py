"""
Gateway适配器基类
定义统一的接口契约，具体Gateway实现继承此类
"""

import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from qtrader.utils.async_event_engine import AsyncEventEngine
from qtrader.app_context import get_app_context
from typing import Any

import pandas as pd

ctx = get_app_context()

from qtrader.models.object import (
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
from qtrader.utils.logger import get_logger

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
        self.md_connected: bool = False  # 行情连接状态
        self.td_connected: bool = False  # 交易连接状态
        self.trading_day: str | None = None
        self.contracts: dict[str, ContractData] = {}
        self._contracts_update_date: str | None = None
        self._event_engine: AsyncEventEngine | None = ctx.get_event_engine()
        logger.info(f"{self.gateway_name} Gateway 初始化完成")

    async def close(self):
        """关闭Gateway连接"""
        self.running = False
        await self.disconnect()
        logger.info(f"{self.gateway_name} Gateway 已关闭")

    @property
    def connected(self) -> bool:
        """网关是否已连接（行情和交易都连接时为True）"""
        return self.md_connected and self.td_connected

    def std_symbol(self, symbol: str) -> str | None:
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

    def load_contracts(self) -> (dict[str, ContractData]) | None:
        """
        从数据库加载合约信息

        从共享数据库（qtrader.db）读取合约信息，该数据库由 Manager 进程维护。

        Returns:
            合约信息字典，如果没有则返回None
        """
        update_date = datetime.now().strftime("%Y-%m-%d")

        try:
            from qtrader.models.po import ContractPo
            from qtrader.utils.database import session_scope

            with session_scope() as session:
                contract_pos = (
                    session.query(ContractPo).filter(ContractPo.update_date == update_date).all()
                )

                if not contract_pos:
                    logger.info(f"数据库中没有更新日期为 {update_date} 的合约信息")
                    return None

                loaded_count = self._parse_contract_pos(contract_pos)
                self._contracts_update_date = update_date
                logger.info(f"从数据库加载了 {loaded_count} 个合约信息 (更新日期: {update_date})")
                return self.contracts
        except Exception as e:
            logger.error(f"从数据库加载合约信息失败: {e}")
            return None

    def _parse_contract_pos(self, contract_pos: list) -> int:
        """
        解析合约PO对象列表并写入内存缓存

        Args:
            contract_pos: ContractPo 对象列表

        Returns:
            成功加载的合约数量
        """
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
                min_open_volume=po.min_open_volume,  # type: ignore[arg-type]
                option_strike=float(po.option_strike) if po.option_strike else None,
                option_underlying=po.option_underlying,  # type: ignore[arg-type]
                option_type=po.option_type,  # type: ignore[arg-type]
            )  # type: ignore[call-arg]
            self.contracts[contract.symbol] = contract
            loaded_count += 1
        return loaded_count

    def load_contracts_from_init_data(self, contracts: list) -> int:
        """
        从 Manager 推送的公共数据中加载合约信息

        此方法由 Trader 在收到 init_public_data 消息时调用，
        将 Manager 推送的合约字典列表直接转换为 ContractData 对象存入缓存，
        无需访问数据库。

        Args:
            contracts: 合约信息字典列表，格式与 ContractInfo.to_dict() 一致

        Returns:
            成功加载的合约数量
        """
        loaded_count = 0
        update_date = datetime.now().strftime("%Y-%m-%d")

        for contract_dict in contracts:
            try:
                symbol_full = contract_dict.get("symbol", "")
                # symbol 可能为 "rb2505" 或 "SHFE.rb2505"
                symbol = symbol_full.split(".")[1] if "." in symbol_full else symbol_full

                exchange_id = contract_dict.get("exchange_id", "")
                exchange = Exchange.from_str(exchange_id)
                if exchange == Exchange.NONE:
                    logger.debug(f"跳过未知交易所合约: {symbol_full} ({exchange_id})")
                    continue

                contract = ContractData(
                    symbol=symbol,  # type: ignore[arg-type]
                    exchange=exchange,
                    name=contract_dict.get("instrument_name") or symbol,  # type: ignore[arg-type]
                    product_type=ProductType.FUTURES,
                    multiple=contract_dict.get("volume_multiple", 1),  # type: ignore[arg-type]
                    pricetick=float(contract_dict.get("price_tick", 0.01)),
                    min_volume=contract_dict.get("min_volume", 1),  # type: ignore[arg-type]
                    option_strike=(
                        float(contract_dict["option_strike"])
                        if contract_dict.get("option_strike")
                        else None
                    ),
                    option_underlying=contract_dict.get("option_underlying"),  # type: ignore[arg-type]
                    option_type=contract_dict.get("option_type"),  # type: ignore[arg-type]
                )  # type: ignore[call-arg]
                self.contracts[contract.symbol] = contract
                loaded_count += 1
            except Exception as e:
                logger.warning(f"解析合约数据失败 [{contract_dict.get('symbol')}]: {e}")

        if loaded_count > 0:
            self._contracts_update_date = update_date
            logger.info(f"从 Manager 公共数据加载了 {loaded_count} 个合约信息")

        return loaded_count

    
    def emit_event(self, event_type: str, data: Any) -> None:
        """
        触发事件

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        self._event_engine.put(event_type, data)

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
    def get_trading_day(self) -> str | None:
        """
        获取当前交易日

        Returns:
            str | None: 交易日日期（YYYYMMDD）
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
    def send_order(self, req: OrderRequest) -> OrderData | None:
        """
        下单

        Args:
            req: 下单请求

        Returns:
            OrderData | None: 报单信息，失败返回None
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
    def get_account(self) -> AccountData | None:
        """
        查询账户信息

        Returns:
            AccountData | None: 账户数据
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
            dict[str, ContractData]: 合约字典 {symbol: ContractData}
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
    def refresh_contracts(self) -> bool:
        """
        强制刷新合约信息，从网关接口重新查询并更新数据库

        Returns:
            bool: 刷新是否成功
        """
        pass

    @abstractmethod
    def get_kline(self, symbol: str, interval: str) -> pd.DataFrame | None:
        """
        获取K线数据

        Args:
            symbol: 合约代码
            interval: 周期（如"M1"）

        Returns:
            pd.DataFrame | None: K线数据框，失败返回None
        """
        pass
