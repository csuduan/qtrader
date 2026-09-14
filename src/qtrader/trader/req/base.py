"""
Trader 请求处理器基类

各领域 handler 模块继承此基类，共享 trader 上下文。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    from qtrader.trader.trader import Trader

logger = get_logger(__name__)


class BaseReqHandler:
    """请求处理器基类"""

    def __init__(self, trader: Trader):
        self.trader = trader
        self.account_id = trader.account_id
