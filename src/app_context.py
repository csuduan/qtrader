"""
应用上下文管理
提供全局状态访问的统一入口
"""

from typing import Any, Dict, Optional

# 预定义的上下文键


class AppContext:
    KEY_EVENT_ENGINE = "event_engine"
    KEY_EVENT_LOOP = "event_loop"
    KEY_CONFIG = "config"
    KEY_TRADING_ENGINE = "trading_engine"
    KEY_STRATEGY_MANAGER = "strategy_manager"
    KEY_TASK_SCHEDULER = "task_scheduler"
    KEY_SWITCH_POS_MANAGER = "switch_pos_manager"
    KEY_TRADING_MANAGER = "trading_manager"

    """应用上下文"""

    def __init__(self):
        self.container: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """设置上下文值（允许覆盖）"""
        self.container[key] = value

    def register(self, key: str, value: Any) -> None:
        """注册上下文（不允许重复）"""
        if key in self.container:
            raise KeyError(f"上下文 [{key}] 已存在")
        self.container[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文值"""
        return self.container.get(key, default)

    def get_or_raise(self, key: str) -> Any:
        """获取上下文值，不存在时抛出异常"""
        if key not in self.container:
            raise KeyError(f"上下文 [{key}] 不存在")
        return self.container[key]

    def has(self, key: str) -> bool:
        """检查上下文是否存在"""
        return key in self.container

    def remove(self, key: str) -> None:
        """移除上下文"""
        if key in self.container:
            del self.container[key]

    def clear(self) -> None:
        """清空所有上下文"""
        self.container.clear()

    def keys(self) -> list:
        """获取所有上下文键"""
        return list(self.container.keys())

    # 便捷获取方法
    def get_event_engine(self) -> Optional[Any]:
        """获取事件引擎"""
        return self.get(self.KEY_EVENT_ENGINE)

    def get_event_loop(self) -> Optional[Any]:
        """获取主事件循环"""
        return self.get(self.KEY_EVENT_LOOP)

    def get_config(self) -> Optional[Any]:
        """获取配置"""
        return self.get(self.KEY_CONFIG)

    def get_trading_engine(self) -> Optional[Any]:
        """获取交易引擎"""
        return self.get(self.KEY_TRADING_ENGINE)

    def get_strategy_manager(self) -> Optional[Any]:
        """获取策略管理器"""
        return self.get(self.KEY_STRATEGY_MANAGER)

    def get_task_scheduler(self) -> Optional[Any]:
        """获取任务调度器"""
        return self.get(self.KEY_TASK_SCHEDULER)

    def get_switch_pos_manager(self) -> Optional[Any]:
        """获取换仓管理器"""
        return self.get(self.KEY_SWITCH_POS_MANAGER)

    def get_trading_manager(self) -> Optional[Any]:
        """获取交易管理器"""
        return self.get(self.KEY_TRADING_MANAGER)


# 全局应用上下文实例
_app_context: AppContext | None = None


def get_app_context() -> AppContext:
    global _app_context
    if _app_context is None:
        _app_context = AppContext()
    """获取全局应用上下文实例"""
    return _app_context
