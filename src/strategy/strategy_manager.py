"""
策略管理器
负责策略实例化、启动/停止管理、事件路由、参数加载
"""
import csv
import os
from typing import Dict, TYPE_CHECKING, Any, Optional
from abc import ABC, abstractmethod
from datetime import datetime

from src.models.object import (
    TickData,
    BarData,
    OrderData,
    TradeData,
    OrderType,
    Offset,
    Direction,
    Exchange,
    Interval,
)
from src.utils.logger import get_logger
from src.utils.event import EventTypes
from src.config_loader import get_config

if TYPE_CHECKING:
    from src.trading_engine import TradingEngine

logger = get_logger(__name__)

# 全局CSV缓存：{csv_path: {strategy_id: params_dict}}
_csv_cache: Dict[str, Dict[str, dict]] = {}


def load_csv_file(csv_path: str) -> Dict[str, dict]:
    """加载CSV文件到缓存"""
    if csv_path in _csv_cache:
        return _csv_cache[csv_path]

    result = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                strategy_id = row.get('StrategyId', '')
                if strategy_id:
                    result[strategy_id] = row
        _csv_cache[csv_path] = result
        logger.info(f"加载CSV参数文件: {csv_path}, 共 {len(result)} 个策略")
        return result
    except FileNotFoundError:
        logger.warning(f"参数文件不存在: {csv_path}")
        return {}
    except Exception as e:
        logger.error(f"加载CSV参数失败: {e}", exc_info=True)
        return {}


def load_strategy_params(yaml_config: dict, strategy_id: str) -> dict:
    """
    加载策略参数（YAML默认参数 + CSV覆盖）

    Args:
        yaml_config: 从YAML加载的策略配置
        strategy_id: 策略ID

    Returns:
        dict: 合并后的策略参数
    """
    params = yaml_config.copy()
    params_file = params.get('params_file')
    if not params_file:
        return params

    # 构建完整路径
    app_config = get_config()
    csv_path = os.path.join(app_config.paths.params, params_file)

    # 加载CSV参数
    csv_data = load_csv_file(csv_path)
    csv_params = csv_data.get(strategy_id, {})
    if not csv_params:
        return params

    # CSV参数直接覆盖
    for key, value in csv_params.items():
        if value:
            params[key] = value

    return params


from src.strategy.base_strategy import BaseStrategy


class StrategyManager:
    """策略管理器"""

    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.configs: Dict[str, dict] = {}
        self.trading_engine = None
        self.event_engine = None
        self.subscribed_symbols: set = set()
        # 订单ID -> 策略ID 的映射关系
        self.order_strategy_map: Dict[str, str] = {}

    def init(self, config_path: str, trading_engine) -> bool:
        """
        初始化策略管理器

        Args:
            config_path: 策略配置文件路径
            trading_engine: TradingEngine实例

        Returns:
            bool: 初始化是否成功
        """
        import yaml
        try:
            self.trading_engine = trading_engine
            self.event_engine = trading_engine.event_engine

            # 加载配置
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                self.configs = data.get('strategies', {})

            logger.info(f"加载 {len(self.configs)} 个策略配置")

            # 加载并实例化策略
            self._load_strategies()

            # 注册事件到 EventEngine
            self._register_events()

            # 启动所有策略
            self.start_all()

            logger.info("策略管理器初始化完成")
            return True

        except Exception as e:
            logger.error(f"策略管理器初始化失败: {e}", exc_info=True)
            return False

    def _load_strategies(self):
        """从配置加载并实例化策略"""
        from src.strategy import get_strategy_class

        for name, config in self.configs.items():
            if not config.get('enabled', False):
                logger.info(f"策略 {name} 未启用，跳过")
                continue

            strategy_type = config.get('type', name)
            strategy_class = get_strategy_class(strategy_type)
            if strategy_class is None:
                logger.warning(f"未找到策略类: {strategy_type}")
                continue

            # 加载参数（YAML默认参数 + CSV覆盖）
            params = load_strategy_params(config, name)

            # 创建策略实例
            try:
                strategy = strategy_class(name, params)
                strategy.strategy_manager = self
                self.add_strategy(name, strategy)

                # 按需订阅合约行情
                symbol = params.get('symbol', '')
                if symbol:
                    self.subscribe_symbol(symbol)
            except Exception as e:
                logger.error(f"创建策略 {name} 失败: {e}", exc_info=True)

    def _register_events(self):
        """注册策略事件到 EventEngine"""
        if not self.event_engine:
            logger.warning("EventEngine 未设置，跳过事件注册")
            return

        self.event_engine.register(EventTypes.TICK_UPDATE, lambda e: self._dispatch_event('on_tick', e.data))
        self.event_engine.register(EventTypes.KLINE_UPDATE, lambda e: self._dispatch_event('on_bar', e.data))
        self.event_engine.register(EventTypes.ORDER_UPDATE, lambda e: self._dispatch_event('on_order', e.data))
        self.event_engine.register(EventTypes.TRADE_UPDATE, lambda e: self._dispatch_event('on_trade', e.data))

        logger.info("策略事件已注册到EventEngine")

    def _dispatch_event(self, method: str, data: Any):
        """
        分发事件到策略

        - 行情事件（on_tick, on_bar）：分发给所有活跃策略
        - 订单/成交事件（on_order, on_trade）：根据订单ID分发给对应策略
        """
        # 订单和成交事件需要根据订单ID分发给对应策略
        if method in ('on_order', 'on_trade'):
            order_id = None
            if isinstance(data, dict):
                order_id = data.get('order_id')
            elif hasattr(data, 'order_id'):
                order_id = data.order_id
            elif method == 'on_trade' and hasattr(data, 'order_id'):
                order_id = data.order_id

            if order_id:
                strategy_id = self.order_strategy_map.get(order_id)
                if strategy_id and strategy_id in self.strategies:
                    strategy = self.strategies[strategy_id]
                    if strategy.active:
                        try:
                            getattr(strategy, method)(data)
                        except Exception as e:
                            logger.exception(f"策略 {strategy_id} {method} 失败: {e}")
                    return
        else:
            # 其他事件分发给所有活跃策略
            for name, strategy in self.strategies.items():
                if strategy.active:
                    try:
                        getattr(strategy, method)(data)
                    except Exception as e:
                        logger.exception(f"策略 {name} {method} 失败: {e}")

    def load_config(self, config_path: str, trading_engine=None) -> bool:
        """加载策略配置（兼容旧接口）"""
        import yaml
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                self.configs = data.get('strategies', {})
                if trading_engine:
                    self.trading_engine = trading_engine
                    self.event_engine = trading_engine.event_engine
                logger.info(f"加载 {len(self.configs)} 个策略配置")
                return True
        except Exception as e:
            logger.error(f"加载策略配置失败: {e}")
            return False

    def load_strategies_from_config(self, trading_engine=None):
        """从配置文件加载并实例化策略（兼容旧接口）"""
        from src.strategy import get_strategy_class

        if trading_engine:
            self.trading_engine = trading_engine
            self.event_engine = trading_engine.event_engine

        for name, config in self.configs.items():
            if not config.get('enabled', False):
                continue

            strategy_type = config.get('type', name)
            strategy_class = get_strategy_class(strategy_type)
            if strategy_class is None:
                continue

            params = load_strategy_params(config, name)

            try:
                strategy = strategy_class(name, params)
                strategy.strategy_manager = self
                self.add_strategy(name, strategy)

                symbol = params.get('symbol', '')
                if symbol:
                    self.subscribe_symbol(symbol)
            except Exception as e:
                logger.error(f"创建策略 {name} 失败: {e}", exc_info=True)

    def add_strategy(self, name: str, strategy: BaseStrategy):
        """添加策略"""
        self.strategies[name] = strategy
        strategy.init()
        logger.info(f"添加策略: {name}")

    def start_strategy(self, name: str) -> bool:
        """启动策略"""
        if name not in self.strategies:
            return False
        return self.strategies[name].start()

    def stop_strategy(self, name: str) -> bool:
        """停止策略"""
        if name not in self.strategies:
            return False
        return self.strategies[name].stop()

    def start_all(self):
        """启动所有已启用的策略"""
        for name, config in self.configs.items():
            if config.get('enabled', False) and name in self.strategies:
                self.start_strategy(name)

    def stop_all(self):
        """停止所有策略"""
        for name in self.strategies:
            self.stop_strategy(name)

    def reset_all_for_new_day(self):
        """重置所有策略（开盘前调用）"""
        for name, strategy in self.strategies.items():
            strategy.reset_for_new_day()
        logger.info("所有策略已重置")

    def subscribe_symbol(self, symbol: str) -> bool:
        """订阅合约行情（按需订阅）"""
        if symbol in self.subscribed_symbols:
            return True
        if self.trading_engine:
            result = self.trading_engine.subscribe_symbol(symbol)
            if result:
                self.subscribed_symbols.add(symbol)
                logger.info(f"订阅合约行情: {symbol}")
            return result
        return False

    def get_status(self) -> list:
        """获取所有策略状态"""
        return [
            {
                "strategy_id": s.strategy_id,
                "active": s.active,
                "config": s.config
            }
            for s in self.strategies.values()
        ]

    # ==================== 交易接口 ====================

    def buy(self, strategy_id: str, symbol: str, volume: int, price: Optional[float] = None,
            offset: Offset = Offset.OPEN) -> Optional[str]:
        """
        买入 - 通过 TradingEngine

        Args:
            strategy_id: 策略ID
            symbol: 合约代码
            volume: 手数
            price: 价格（None为市价）
            offset: 开平标识

        Returns:
            委托单ID
        """
        if not self.trading_engine:
            logger.warning(f"TradingEngine 未设置，无法执行买入")
            return None

        try:
            order_id = self.trading_engine.insert_order(
                symbol=symbol,
                direction=Direction.BUY.value,
                offset=offset.value,
                volume=volume,
                price=price or 0
            )
            if order_id:
                # 记录订单与策略的映射关系
                self.order_strategy_map[order_id] = strategy_id
                logger.info(f"策略 [{strategy_id}] 买入: {symbol} {volume}手 @{price or '市价'} -> 订单ID: {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"策略 [{strategy_id}] 买入失败: {e}")
            return None

    def sell(self, strategy_id: str, symbol: str, volume: int, price: Optional[float] = None,
             offset: Offset = Offset.CLOSE) -> Optional[str]:
        """
        卖出 - 通过 TradingEngine

        Args:
            strategy_id: 策略ID
            symbol: 合约代码
            volume: 手数
            price: 价格（None为市价）
            offset: 开平标识

        Returns:
            委托单ID
        """
        if not self.trading_engine:
            logger.warning(f"TradingEngine 未设置，无法执行卖出")
            return None

        try:
            order_id = self.trading_engine.insert_order(
                symbol=symbol,
                direction=Direction.SELL.value,
                offset=offset.value,
                volume=volume,
                price=price or 0
            )
            if order_id:
                # 记录订单与策略的映射关系
                self.order_strategy_map[order_id] = strategy_id
                logger.info(f"策略 [{strategy_id}] 卖出: {symbol} {volume}手 @{price or '市价'} -> 订单ID: {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"策略 [{strategy_id}] 卖出失败: {e}")
            return None

    def cancel_order(self, strategy_id: str, order_id: str) -> bool:
        """
        撤单 - 通过 TradingEngine

        Args:
            strategy_id: 策略ID
            order_id: 订单ID

        Returns:
            是否成功
        """
        if not self.trading_engine:
            logger.warning(f"TradingEngine 未设置，无法执行撤单")
            return False

        try:
            # 验证订单是否属于该策略
            mapped_strategy_id = self.order_strategy_map.get(order_id)
            if mapped_strategy_id and mapped_strategy_id != strategy_id:
                logger.warning(f"订单 {order_id} 属于策略 {mapped_strategy_id}，策略 {strategy_id} 无法撤销")
                return False

            success = self.trading_engine.cancel_order(order_id)
            if success:
                logger.info(f"策略 [{strategy_id}] 撤单成功: {order_id}")
            return success
        except Exception as e:
            logger.error(f"策略 [{strategy_id}] 撤单失败: {e}")
            return False
