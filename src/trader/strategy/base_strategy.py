"""
策略基类（异步版本）
定义策略的接口和基本功能
"""

from datetime import datetime, time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, Field

from src.models.object import (
    BarData,
    Offset,
    OrderData,
    TickData,
    TradeData,
    Direction,
    Offset,
)
from src.trader.order_cmd import OrderCmd
from src.utils.config_loader import StrategyConfig
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.models.object import PositionData
    from src.trader.strategy_manager import StrategyManager

logger = get_logger(__name__)


class BaseParam(BaseModel):
    """策略公共参数"""
    symbol: str = Field(default="IM2603", title="合约代码")
    bar_type: str = Field(default="M1", title="bar类型")
    volume: int = Field(default=1, title="目标手数")
    slip: float = Field(default=0, title="滑点")
    max_position: int = Field(default=50, title="最大持仓")
    volume_per_order: int = Field(default=5, title="单次下单手数")
    order_timeout: int = Field(default=10, title="报单超时")
    cmd_timeout: int = Field(default=300, title="指令超时")
    take_profit_pct: float = Field(default=0.0, title="止盈率")
    stop_loss_pct: float = Field(default=0.0, title="止损率")
    overnight: bool = Field(default=False, title="隔夜持仓")
    force_exit_time: time = Field(default=time(14, 45, 0), title="强平时间")

    def get_param_definitions(self) -> List[Dict[str, Any]]:
        """获取参数定义列表"""
        definitions = []
        for field_name, field_info in self.model_fields.items():
            # 获取Field元数据
            title = field_info.title or field_name
            # 推断类型
            if field_info.annotation == int:
                param_type = "int"
            elif field_info.annotation == float:
                param_type = "float"
            elif field_info.annotation == bool:
                param_type = "bool"
            elif field_info.annotation == time:
                param_type = "time"
            else:
                param_type = "string"

            definitions.append({
                "key": field_name,
                "label": title,
                "type": param_type,
                "value": getattr(self, field_name)
            })
        return definitions

class Signal(BaseModel):
    """策略信号基类"""

    side: int = 0  # 信号方向: 1多头, -1空头, 0无信号
    entry_price: float = 0.0  # 开仓价格
    entry_time: Optional[datetime] = None  # 开仓时间
    entry_volume: int = 0  # 开仓目标手数
    exit_price: float = 0.0  # 平仓价格
    exit_time: Optional[datetime] = None  # 平仓时间
    exit_reason: str = ""  # 平仓原因

    def __str__(self) -> str:
        return (
            f"Signal(side={self.side}, "
            f"entry_price={self.entry_price}, entry_time={self.entry_time}, exit_price={self.exit_price}, "
            f"exit_time={self.exit_time}, exit_reason={self.exit_reason})"
        )


class BaseStrategy:
    """策略基类（异步版本）"""

    # 订阅bar列表（格式："symbol-interval"）
    def __init__(self, strategy_id: str, strategy_config: StrategyConfig):
        self.strategy_id = strategy_id
        self.config: StrategyConfig = strategy_config
        self.symbol: str =strategy_config.symbol
        self.bar_type: str =strategy_config.bar
        self.inited: bool = False
        self.enabled: bool = True
        self.bar_subscriptions: List[str] = []
        self.trading_day: Optional[datetime] = None
        # 策略管理器引用
        self.strategy_manager: Optional["StrategyManager"] = None
        # 参数模型（子类覆盖）
        self.param: Optional[BaseParam] = None

        # 信号及持仓
        self.signal: Optional[Signal] = None
        self.pos_volume: int = 0  # 持仓手数(净手数)
        self.pos_price: Optional[float] = None  # 持仓均价

        # 暂停状态
        self.opening_paused: bool = False
        self.closing_paused: bool = False

        # 运行中信息
        self._pending_cmd: Optional[OrderCmd] = None
        self._hist_cmds: Dict[str, OrderCmd] = {}


    def init(self,trading_day: datetime) -> bool:
        """策略初始化"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        self._pending_cmd = None
        self._hist_cmds = {}
        self.signal = None
        self.pos_volume = 0
        self.pos_price = None
        self.trading_day = trading_day

        # 解析参数
        if self.config.params:
            self.param = BaseParam.model_validate(self.config.params)
            self.symbol = self.param.symbol

        return True

    def get_params(self) -> List[Dict[str, Any]]:
        """获取策略参数（包含元数据）"""
        # 获取基础参数定义
        if not self.param:
            return []
        definitions = self.param.get_param_definitions()
        return definitions
    
    def load_hist_bars(self, symbol: str, start: datetime, end: datetime) -> List[BarData]:
        """加载历史K线数据"""
        if self.strategy_manager is None:
            logger.error(f"策略 [{self.strategy_id}] 的 strategy_manager 未初始化")
            return []
        return self.strategy_manager.load_hist_bars(symbol, self.bar_type, start, end)

    def get_signal(self) -> Optional[Dict[str, Any]]:
        """获取当前信号"""
        return self.signal.model_dump() if self.signal else None

    def update_params(self, params: Dict[str, Any]) -> None:
        """
        更新策略参数（只更新内存，不写入文件）

        Args:
            params: 要更新的参数字典
        """
        for key, value in params.items():
            if hasattr(self.param, key):
                setattr(self.param, key, value)
            else:
                logger.warning(f"策略 [{self.strategy_id}] 参数 {key} 不存在")

        logger.info(f"策略 [{self.strategy_id}] 参数已更新: {params}")

    def update_signal(self, signal: Dict[str, Any]) -> None:
        """
        更新策略信号（只更新内存，不写入文件）

        Args:
            signal: 要更新的信号字典
        """
        if not self.signal:
            self.signal = Signal()

        for key, value in signal.items():
            if hasattr(self.signal, key):
                # 处理datetime类型的参数
                if key in ["entry_time", "exit_time"] and isinstance(value, str):
                    try:
                        value = datetime.fromisoformat(value)
                    except ValueError:
                        pass
                setattr(self.signal, key, value)

        logger.info(f"策略 [{self.strategy_id}] 信号已更新: side={self.signal.side}")

    async def execute_signal(self) -> None:
        """执行信号"""
        if not self.signal or self.param is None:
            return
        signal = self.signal
        if signal.exit_time:
            # 平仓处理
            if self._pending_cmd and not self._pending_cmd.is_finished:
                # 有进行中的指令
                if self._pending_cmd.offset == Offset.OPEN:
                    # 有未完成的开仓操作，等待下一次执行
                    logger.info(f"策略 [{self.strategy_id}] 有未完成的开仓指令，先取消指令，等待下一次执行")
                    # 当前开仓报单未完成，先撤单，等待下一次执行平仓
                    await self.cancel_order_cmd(self._pending_cmd)
                    return
            else:
                # 无进行中的指令
                # 当前信号持有手数>0
                if self.pos_volume > 0:
                    exit_cmd = OrderCmd(
                        symbol=self.param.symbol,
                        offset=Offset.CLOSE,
                        direction=Direction.SELL if signal.side == 1 else Direction.BUY,
                        volume=self.pos_volume,
                        price=0
                    )
                await self.send_order_cmd(exit_cmd)
        else:
            # 开仓处理
            if self._pending_cmd and not self._pending_cmd.is_finished:
                #有进行中的指令
                pass
            else:
                if self.pos_volume < self.param.volume:
                    entry_cmd = OrderCmd(
                        symbol=self.param.symbol,
                        offset=Offset.OPEN,
                        direction=Direction.BUY if signal.side == 1 else Direction.SELL,
                        volume=self.param.volume - self.pos_volume,
                        price=0
                    )
                    await self.send_order_cmd(entry_cmd)

    def _on_cmd_change(self, cmd: OrderCmd):
        """处理订单状态变化"""
        if not cmd.is_finished or not self._pending_cmd:
            return    
        # 等报单指令完成，指令中的成交数量不会变化了，再更新持仓     
        if cmd.cmd_id == self._pending_cmd.cmd_id:
            #有进行中的指令  
            if cmd.offset == Offset.OPEN:
                # 开仓指令
                self.pos_volume += cmd.filled_volume
                self.pos_price = cmd.filled_price #后期是否要考虑平均持仓价
            elif cmd.offset == Offset.CLOSE:
                # 平仓指令
                self.pos_volume -= cmd.filled_volume            
            self._pending_cmd = None

            if "报单被拒" in cmd.finish_reason:
                if cmd.offset == Offset.OPEN:
                    self.opening_paused = True
                elif cmd.offset == Offset.CLOSE:
                    self.closing_paused = True
                return
            return

    def get_trading_status(self) -> str:
        """是否正在交易中(开仓中，平仓中)"""
        if self._pending_cmd and not self._pending_cmd.is_finished:
            return "开仓中" if self._pending_cmd.offset == Offset.OPEN else "平仓中"
        return ""

    def enable(self,status:bool=True) -> bool:
        """启用策略"""
        self.enabled = status
        logger.info(f"策略 [{self.strategy_id}] 启用" if status else "禁用")
        return True

    # ==================== 事件回调（异步版本）====================
    async def on_tick(self, tick: TickData):
        """Tick行情回调（异步版本）"""
        pass

    async def on_bar(self, bar: BarData):
        """Bar行情回调（异步版本）"""
        pass

    async def on_order(self, order: OrderData):
        """订单状态回调（异步版本）"""
        pass

    async def on_trade(self, trade: TradeData):
        """成交回调（异步版本）"""
        pass

    # ==================== 交易接口 ====================
    async def send_order_cmd(self, order_cmd: OrderCmd):
        """发送报单指令"""
        if self.param is None:
            logger.error(f"策略 [{self.strategy_id}] 的参数未初始化")
            return
        if order_cmd.offset == Offset.CLOSE and self.closing_paused:
            logger.warning(f"策略 [{self.strategy_id}] 暂停平仓")
            return
        if order_cmd.offset == Offset.OPEN and self.opening_paused:
            logger.warning(f"策略 [{self.strategy_id}] 暂停开仓")
            return

        self._pending_cmd = order_cmd
        self._hist_cmds[order_cmd.cmd_id] = order_cmd
        if order_cmd.on_change is None:
            order_cmd.on_change = self._on_cmd_change

        order_cmd.source = f"策略-{self.strategy_id}"
        order_cmd.order_timeout = self.param.order_timeout
        order_cmd.cmd_timeout = self.param.cmd_timeout
        order_cmd.volume_per_order = self.param.volume_per_order
        if self.strategy_manager is None:
            logger.error(f"策略 [{self.strategy_id}] 的 strategy_manager 未初始化")
            return
        await self.strategy_manager.send_order_cmd(self.strategy_id, order_cmd)

    async def cancel_order_cmd(self, order_cmd: OrderCmd):
        """取消报单指令"""
        if self.strategy_manager is None:
            logger.error(f"策略 [{self.strategy_id}] 的 strategy_manager 未初始化")
            return
        await self.strategy_manager.cancel_order_cmd(self.strategy_id, order_cmd)

    def set_opening_paused(self, paused: bool) -> None:
        """
        设置开仓暂停状态

        Args:
            paused: True-暂停开仓, False-恢复开仓
        """
        self.opening_paused = paused
        status = "暂停" if paused else "恢复"
        logger.info(f"策略 [{self.strategy_id}] 开仓已{status}")

    def set_closing_paused(self, paused: bool) -> None:
        """
        设置平仓暂停状态

        Args:
            paused: True-暂停平仓, False-恢复平仓
        """
        self.closing_paused = paused
        status = "暂停" if paused else "恢复"
        logger.info(f"策略 [{self.strategy_id}] 平仓已{status}")


    def get_position(self, symbol: str) -> Optional["PositionData"]:
        """
        获取指定合约的持仓信息

        Args:
            symbol: 合约代码

        Returns:
            PositionData: 持仓数据，如果不存在则返回None
        """
        if self.strategy_manager and self.strategy_manager.trading_engine:
            return self.strategy_manager.get_position(symbol)
        return None
