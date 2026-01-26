"""
CTP Gateway适配器框架
实现BaseGateway接口，参考qts实现
（注：实际使用需要安装CTP SDK）
"""
from typing import Optional, Dict
from datetime import datetime

from src.adapters.base_gateway import BaseGateway
from src.models.object import (
    TickData, BarData, OrderData, TradeData,
    PositionData, AccountData, ContractData,
    SubscribeRequest, OrderRequest, CancelRequest,
    Direction, Offset, OrderStatus, Exchange
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class CtpGateway(BaseGateway):
    """CTP Gateway适配器（框架实现）"""

    gateway_name = "CTP"

    def __init__(self):
        super().__init__()
        # CTP API占位
        self._api = None
        self._front_id: int = 0
        self._session_id: int = 0
        self._max_order_ref: int = 0

        # 数据缓存
        self._orders: Dict[str, OrderData] = {}
        self._trades: Dict[str, TradeData] = {}

    # ==================== 连接管理 ====================

    def connect(self) -> bool:
        """连接CTP接口（待实现）"""
        logger.warning(f"{self.gateway_name} 适配器需要CTP SDK支持")
        return False

    def disconnect(self) -> bool:
        """断开CTP连接（待实现）"""
        self.connected = False
        return True

    # ==================== 行情订阅 ====================

    def subscribe(self, req: SubscribeRequest) -> bool:
        """订阅行情（待实现）"""
        logger.warning("订阅行情功能待实现")
        return False

    def unsubscribe(self, req: SubscribeRequest) -> bool:
        """取消订阅（待实现）"""
        return False

    # ==================== 交易接口 ====================

    def send_order(self, req: OrderRequest) -> Optional[str]:
        """下单（待实现）"""
        logger.warning("下单功能待实现，需要CTP SDK")
        return None

    def cancel_order(self, req: CancelRequest) -> bool:
        """撤单（待实现）"""
        logger.warning("撤单功能待实现，需要CTP SDK")
        return False

    # ==================== 查询接口 ====================

    def query_account(self) -> Optional[AccountData]:
        """查询账户（待实现）"""
        return None

    def query_position(self) -> list[PositionData]:
        """查询持仓（待实现）"""
        return []

    def query_orders(self) -> list[OrderData]:
        """查询活动订单"""
        return list(self._orders.values())

    def query_trades(self) -> list[TradeData]:
        """查询今日成交"""
        return list(self._trades.values())

    def query_contracts(self) -> Dict[str, ContractData]:
        """查询合约（待实现）"""
        return {}

    # ==================== 数据转换占位 ====================

    def _convert_direction(self, direction: str) -> str:
        """转换买卖方向"""
        return direction

    def _convert_offset(self, offset: str) -> str:
        """转换开平标志"""
        return offset

    def _convert_status(self, status: str) -> OrderStatus:
        """转换订单状态"""
        status_map = {
            "0": OrderStatus.NOTTRADED,
            "1": OrderStatus.PARTTRADED,
            "2": OrderStatus.ALLTRADED,
            "3": OrderStatus.CANCELLED,
            "4": OrderStatus.REJECTED,
        }
        return status_map.get(status, OrderStatus.SUBMITTING)
