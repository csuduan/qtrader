"""
全局状态管理模块
用于在不同模块间共享全局状态
"""
from typing import Optional

from src.config_loader import AppConfig
from src.trading_engine import TradingEngine
from src.utils.event import EventTypes, event_engine
from src.switch_mgr import SwitchPosManager
from src.strategy.strategy_manager import StrategyManager
from src.scheduler import TaskScheduler



trading_engine: Optional[TradingEngine] = None
strategy_manager: Optional[StrategyManager] = None
config: AppConfig = None
task_scheduler: Optional[TaskScheduler] = None
switch_pos_manager: Optional[SwitchPosManager] = None



def set_trading_engine(engine: TradingEngine):
    """设置全局交易引擎实例"""
    global trading_engine
    trading_engine = engine


def get_trading_engine() -> Optional[TradingEngine]:
    """获取全局交易引擎实例"""
    return trading_engine


def set_config(cfg: AppConfig):
    """设置全局配置实例"""
    global config
    config = cfg


def get_config() -> AppConfig:
    """获取全局配置实例"""
    return config


def set_task_scheduler(scheduler):
    """设置全局任务调度器实例"""
    global task_scheduler
    task_scheduler = scheduler


def get_task_scheduler():
    """获取全局任务调度器实例"""
    return task_scheduler

def set_switch_pos_manager(manager):
    """设置全局换仓管理器实例"""
    global switch_pos_manager
    switch_pos_manager = manager


def get_switch_pos_manager() -> Optional[SwitchPosManager]:
    """获取全局换仓管理器实例"""
    return switch_pos_manager

def get_strategy_manager() -> Optional[StrategyManager]:
    """获取全局策略管理器实例"""
    from src.strategy.strategy_manager import StrategyManager
    return strategy_manager

def set_strategy_manager(manager: StrategyManager):
    """设置全局策略管理器实例"""
    global strategy_manager
    strategy_manager = manager