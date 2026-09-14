"""
qtrader 策略模块

提供策略基类、策略管理器和具体策略实现
"""

from typing import TYPE_CHECKING

from qtrader.trader.strategy.base_strategy import BaseParam, BaseStrategy
from qtrader.trader.strategy.strategy_rsi import RsiStrategy

if TYPE_CHECKING:
    from qtrader.trader.strategy_manager import StrategyManager, load_strategy_params

__all__ = [
    "BaseStrategy",
    "BaseParam",
    "StrategyManager",
    "load_strategy_params",
    "RsiStrategy",
    "create_strategy",
]

# 策略注册表，用于动态加载
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "rsi_strategy": RsiStrategy,
}


def get_strategy_class(strategy_type: str) -> type[BaseStrategy] | None:
    """根据策略类型获取策略类"""
    return STRATEGY_REGISTRY.get(strategy_type)


def register_strategy(strategy_type: str, strategy_class: type[BaseStrategy]) -> None:
    """注册新策略类型"""
    STRATEGY_REGISTRY[strategy_type] = strategy_class
