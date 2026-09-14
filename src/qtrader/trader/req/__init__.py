"""
Trader Socket请求处理器（组合入口）

按领域拆分到 trader/req/ 下各模块，此处组合注册。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtrader.trader.req.connection import ConnectionReqHandler
from qtrader.trader.req.misc import MiscReqHandler
from qtrader.trader.req.rotation import RotationReqHandler
from qtrader.trader.req.strategy import StrategyReqHandler
from qtrader.trader.req.system import SystemReqHandler
from qtrader.trader.req.target import TargetReqHandler
from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    from qtrader.trader.trader import Trader
    from qtrader.utils.ipc import SocketServer

logger = get_logger(__name__)


class TraderReqHandler:
    """
    Socket请求处理器

    将各领域请求处理器注册到 SocketServer。
    """

    # 领域 handler 类，按依赖顺序排列
    HANDLER_CLASSES = [
        ConnectionReqHandler,
        StrategyReqHandler,
        RotationReqHandler,
        TargetReqHandler,
        SystemReqHandler,
        MiscReqHandler,
    ]

    def __init__(self, trader: Trader):
        self.trader = trader
        self.account_id = trader.account_id
        self.handlers = [cls(trader) for cls in self.HANDLER_CLASSES]

    def __getattr__(self, name: str) -> Any:
        """将 _req_*/辅助方法访问转发到对应领域 handler"""
        for handler in self.handlers:
            if hasattr(handler, name):
                return getattr(handler, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def register_to(self, socket_server: SocketServer) -> None:
        """将所有领域 handler 注册到 SocketServer"""
        for handler in self.handlers:
            socket_server.register_handlers_from_instance(handler)
        logger.info(f"Trader [{self.account_id}] 已注册 {len(self.handlers)} 个领域请求处理器")
