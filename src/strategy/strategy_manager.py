"""
策略管理器
负责策略实例化、启动/停止管理、事件路由、参数热加载
"""
from typing import Dict, Optional, Callable
from abc import ABC, abstractmethod

from src.models.object import TickData, BarData, OrderData, TradeData
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BaseStrategy(ABC):
    """策略基类"""

    def __init__(self, strategy_id: str, config: dict):
        self.strategy_id = strategy_id
        self.config = config
        self.active: bool = False
        self.inited: bool = False

        # 交易接口（由上层注入）
        self.gateway = None

    # ==================== 生命周期 ====================

    def init(self) -> bool:
        """策略初始化"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        return True

    def start(self) -> bool:
        """启动策略"""
        if not self.inited:
            self.init()
        self.active = True
        logger.info(f"策略 [{self.strategy_id}] 启动")
        return True

    def stop(self) -> bool:
        """停止策略"""
        self.active = False
        logger.info(f"策略 [{self.strategy_id}] 停止")
        return True

    def reload(self) -> bool:
        """重新加载策略参数"""
        logger.info(f"策略 [{self.strategy_id}] 重新加载参数...")
        return True

    # ==================== 事件回调 ====================

    @abstractmethod
    def on_tick(self, tick: TickData):
        """Tick行情回调"""
        pass

    @abstractmethod
    def on_bar(self, bar: BarData):
        """Bar行情回调"""
        pass

    def on_order(self, order: OrderData):
        """订单状态回调"""
        pass

    def on_trade(self, trade: TradeData):
        """成交回调"""
        pass

    # ==================== 交易接口 ====================

    def buy(self, symbol: str, volume: int, price: Optional[float] = None,
            offset: Offset = Offset.OPEN) -> Optional[str]:
        """买入"""
        if not self.active or not self.gateway:
            return None
        from src.models.object import OrderRequest, Direction
        req = OrderRequest(
            symbol=symbol,
            direction=Direction.BUY,
            offset=offset,
            volume=volume,
            price=price
        )
        return self.gateway.send_order(req)

    def sell(self, symbol: str, volume: int, price: Optional[float] = None,
             offset: Offset = Offset.CLOSE) -> Optional[str]:
        """卖出"""
        if not self.active or not self.gateway:
            return None
        from src.models.object import OrderRequest, Direction
        req = OrderRequest(
            symbol=symbol,
            direction=Direction.SELL,
            offset=offset,
            volume=volume,
            price=price
        )
        return self.gateway.send_order(req)

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        if not self.active or not self.gateway:
            return False
        from src.models.object import CancelRequest
        req = CancelRequest(order_id=order_id)
        return self.gateway.cancel_order(req)


class StrategyManager:
    """策略管理器"""

    def __init__(self):
        self.strategies: Dict[str, BaseStrategy] = {}
        self.configs: Dict[str, dict] = {}

    def load_config(self, config_path: str) -> bool:
        """加载策略配置"""
        import yaml
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                self.configs = data.get('strategies', {})
                logger.info(f"加载 {len(self.configs)} 个策略配置")
                return True
        except Exception as e:
            logger.error(f"加载策略配置失败: {e}")
            return False

    def add_strategy(self, name: str, strategy: BaseStrategy):
        """添加策略"""
        self.strategies[name] = strategy
        strategy.init()
        logger.info(f"添加策略: {name}")

    def start_strategy(self, name: str) -> bool:
        """启动策略"""
        if name not in self.strategies:
            logger.error(f"策略不存在: {name}")
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

    def get_status(self) -> list:
        """获取所有策略状态"""
        status_list = []
        for name, strategy in self.strategies.items():
            status_list.append({
                "strategy_id": strategy.strategy_id,
                "active": strategy.active,
                "config": strategy.config
            })
        return status_list
