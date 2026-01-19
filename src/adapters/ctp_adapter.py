"""
CTP交易接口适配器
将CTP的接口适配到统一的TradingAdapter接口
基于: https://github.com/csuduan/qts-api/tree/main/ctp
"""
from typing import Any, Dict, List, Optional

from src.adapters.base import (
    TradingAdapter,
    AccountInfo,
    PositionInfo,
    TradeInfo,
    OrderInfo,
    QuoteInfo,
)


class CtpAdapter(TradingAdapter):
    """CTP接口适配器（待实现）"""

    def __init__(
        self,
        account_id: str,
        broker_id: str,
        investor_id: str,
        password: str,
        front_addresses: List[str],
    ):
        self.account_id = account_id
        self.broker_id = broker_id
        self.investor_id = investor_id
        self.password = password
        self.front_addresses = front_addresses

    def connect(self) -> bool:
        """连接到CTP接口"""
        raise NotImplementedError("CTP适配器待实现")

    def disconnect(self) -> None:
        """断开连接"""
        raise NotImplementedError("CTP适配器待实现")

    def is_connected(self) -> bool:
        """检查是否已连接"""
        raise NotImplementedError("CTP适配器待实现")

    def get_account(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        raise NotImplementedError("CTP适配器待实现")

    def get_position(self) -> Dict[str, PositionInfo]:
        """获取持仓信息"""
        raise NotImplementedError("CTP适配器待实现")

    def get_trade(self) -> Dict[str, TradeInfo]:
        """获取成交记录"""
        raise NotImplementedError("CTP适配器待实现")

    def get_order(self) -> Dict[str, OrderInfo]:
        """获取委托单信息"""
        raise NotImplementedError("CTP适配器待实现")

    def insert_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        volume: int,
        price: float = 0,
        price_type: str = "LIMIT",
    ) -> Optional[str]:
        """下单"""
        raise NotImplementedError("CTP适配器待实现")

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        raise NotImplementedError("CTP适配器待实现")

    def query_quotes(self, ins_class: List[str] = None, expired: bool = False) -> List[str]:
        """查询合约列表"""
        raise NotImplementedError("CTP适配器待实现")

    def subscribe_quote(self, symbols: List[str]) -> bool:
        """订阅行情"""
        raise NotImplementedError("CTP适配器待实现")

    def wait_update(self) -> Any:
        """等待数据更新"""
        raise NotImplementedError("CTP适配器待实现")

    def is_changing(self, data: Any) -> bool:
        """检查数据是否变化"""
        raise NotImplementedError("CTP适配器待实现")

    def close(self) -> None:
        """关闭连接"""
        self.disconnect()
