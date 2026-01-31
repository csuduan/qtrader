"""
qtrader 策略模块

提供策略基类、策略管理器和具体策略实现
"""

from typing import TYPE_CHECKING

from src.trader.strategy.base_strategy import BaseStrategy
from src.trader.strategy.strategy_rsi import RsiStrategy, create_strategy

if TYPE_CHECKING:
    from src.trader.core.strategy_manager import StrategyManager, load_strategy_params

__all__ = [
    "BaseStrategy",
    "StrategyManager",
    "load_strategy_params",
    "RsiStrategy",
    "create_strategy",
]

# 策略注册表，用于动态加载
STRATEGY_REGISTRY = {
    "rsi_strategy": RsiStrategy,
}


def get_strategy_class(strategy_type: str):
    """根据策略类型获取策略类"""
    return STRATEGY_REGISTRY.get(strategy_type)


def register_strategy(strategy_type: str, strategy_class):
    """注册新策略类型"""
    STRATEGY_REGISTRY[strategy_type] = strategy_class
