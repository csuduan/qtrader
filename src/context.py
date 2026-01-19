"""
全局状态管理模块
用于在不同模块间共享全局状态
"""
from typing import Optional

from src.config_loader import AppConfig
from src.trading_engine import TradingEngine
from src.scheduler import TaskScheduler
from src.account_manager import AccountManager
from src.switch_mgr import SwitchPosManager
from src.utils.event import EventTypes, event_engine



trading_engine: Optional[TradingEngine] = None
config: Optional[AppConfig] = None
task_scheduler: Optional[TaskScheduler] = None
account_manager: Optional[AccountManager] = None
switch_pos_manager: Optional[SwitchPosManager] = None



def set_trading_engine(engine: TradingEngine):
    """设置全局交易引擎实例"""
    global trading_engine
    trading_engine = engine


def get_trading_engine() -> Optional["TradingEngine"]:
    """获取全局交易引擎实例"""
    from src.trading_engine import TradingEngine
    return trading_engine


def set_config(cfg: AppConfig):
    """设置全局配置实例"""
    global config
    config = cfg


def get_config() -> Optional[AppConfig]:
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

def set_account_manager(manager: AccountManager):
    """设置全局账户管理器实例"""
    global account_manager
    account_manager = manager


def get_account_manager() -> Optional[AccountManager]:
    """获取全局账户管理器实例"""
    return account_manager