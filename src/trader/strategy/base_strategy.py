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
    Direction,
    Offset,
    OrderData,
    StrategyPosition,
    TickData,
    TradeData,
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
    lock_position: bool = Field(default=False, title="锁仓模式")

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

            definitions.append(
                {
                    "key": field_name,
                    "label": title,
                    "type": param_type,
                    "value": getattr(self, field_name),
                }
            )
        return definitions


class Signal(BaseModel):
    """策略信号基类"""

    side: int = 0  # 信号方向: 1多头, -1空头, 0无信号
    entry_price: float = 0.0  # 开仓价格
    entry_time: Optional[time] = None  # 开仓时间
    entry_volume: int = 0  # 开仓目标手数
    exit_price: float = 0.0  # 平仓价格
    exit_time: Optional[time] = None  # 平仓时间
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
        # 策略配置
        self.config: StrategyConfig = strategy_config
        # 策略ID
        self.strategy_id = strategy_id
        # 合约代码
        self.symbol: str = strategy_config.symbol
        # 目标手数
        self.volume: int = strategy_config.volume
        # k线类型
        self.bar_type: str = strategy_config.bar

        self.inited: bool = False
        self.enabled: bool = True
        self.bar_subscriptions: List[str] = []
        self.trading_day: Optional[datetime] = None
        # 策略管理器引用
        self.strategy_manager: Optional["StrategyManager"] = None
        # 参数模型（子类覆盖）
        self.param: Optional[BaseParam] = None

        # 策略持仓管理: {symbol -> StrategyPosition}
        self._positions: Dict[str, StrategyPosition] = {}

        # 信号
        self.signal: Optional[Signal] = None

        # 暂停状态
        self.opening_paused: bool = False
        self.closing_paused: bool = False

        # 运行中信息
        self._pending_cmds: List[OrderCmd] = []
        self._hist_cmds: Dict[str, OrderCmd] = {}

    def init(self, trading_day: datetime) -> bool:
        """策略初始化"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        self._pending_cmds = []
        self._hist_cmds = {}
        self.signal = None
        self.trading_day = trading_day

        # 解析参数
        if self.config.params:
            self.param = BaseParam.model_validate(self.config.params)
            self.symbol = self.param.symbol
            self.volume = self.param.volume
        else:
            self.enabled = False
            logger.error(f"策略 [{self.strategy_id}] 未配置参数")
            return False

        return True

    def init_positions(self, positions: List[StrategyPosition]) -> None:
        """
        初始化策略持仓（从数据库加载）

        Args:
            positions: 持仓列表
        """
        self._positions.clear()
        for pos in positions:
            self._positions[pos.symbol] = pos
            logger.info(
                f"策略 [{self.strategy_id}] 加载持仓: {pos.symbol} "
                f"多仓={pos.pos_long}({pos.pos_long_td}/{pos.pos_long_yd}), "
                f"空仓={pos.pos_short}({pos.pos_short_td}/{pos.pos_short_yd})"
            )

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

    def update_signal(self, data: Dict[str, Any]) -> None:
        """
        更新策略信号（只更新内存，不写入文件）

        Args:
            signal: 要更新的信号字典
        """
        if not self.signal:
            self.signal = Signal()

        # 更新信号
        for key, value in data.items():
            if hasattr(self.signal, key):
                # 处理datetime类型的参数
                if key in ["entry_time", "exit_time"] and isinstance(value, str):
                    try:
                        value = datetime.fromisoformat(value)
                    except ValueError:
                        pass
                setattr(self.signal, key, value)

        logger.info(f"策略 [{self.strategy_id}] 信号已更新: side={self.signal.side}")

    def clear_signal(self) -> None:
        """清除策略信号（无信号状态）"""
        if self.signal:
            logger.info(f"策略 [{self.strategy_id}] 信号已清除 (原信号: {self.signal})")
            self.signal = None
        else:
            logger.debug(f"策略 [{self.strategy_id}] 无信号需要清除")

    # ==================== 持仓管理（支持多合约）====================

    def _get_or_create_position(self, symbol: str) -> StrategyPosition:
        """
        获取或创建指定合约的持仓对象

        Args:
            symbol: 合约代码

        Returns:
            StrategyPosition: 持仓对象
        """
        if symbol not in self._positions:
            self._positions[symbol] = StrategyPosition(
                strategy_id=self.strategy_id,
                symbol=symbol,
            )
        return self._positions[symbol]

    def get_position(self, symbol: Optional[str] = None) -> Optional[StrategyPosition]:
        """
        获取指定合约的持仓信息

        Args:
            symbol: 合约代码，默认为None（返回主合约持仓）

        Returns:
            StrategyPosition: 持仓数据，如果不存在则返回None
        """
        symbol = symbol or self.symbol
        return self._positions.get(symbol)

    def get_all_positions(self) -> Dict[str, StrategyPosition]:
        """
        获取所有合约的持仓

        Returns:
            Dict[str, StrategyPosition]: {symbol -> position}
        """
        return self._positions.copy()

    def update_position(self, position_data: Dict[str, Any]) -> None:
        """
        更新策略持仓（兼容旧接口）

        Args:
            position_data: 持仓数据字典，包含 symbol, pos_long, pos_short, pos_price 等
        """
        symbol = position_data.get("symbol", self.symbol)
        pos = self._get_or_create_position(symbol)

        if "pos_long" in position_data:
            pos_long = position_data["pos_long"]
            # 默认分配到昨仓（兼容旧数据）
            pos.pos_long_yd = pos_long
            pos.pos_long_td = 0
        if "pos_short" in position_data:
            pos_short = position_data["pos_short"]
            # 默认分配到昨仓（兼容旧数据）
            pos.pos_short_yd = pos_short
            pos.pos_short_td = 0
        if "pos_price" in position_data:
            price = position_data["pos_price"]
            pos.avg_price_long = price
            pos.avg_price_short = price

        pos.updated_at = datetime.now()
        logger.info(
            f"策略 [{self.strategy_id}] 持仓已更新: {symbol} "
            f"多仓={pos.pos_long}({pos.pos_long_td}/{pos.pos_long_yd}), "
            f"空仓={pos.pos_short}({pos.pos_short_td}/{pos.pos_short_yd})"
        )

    def load_positions(self, positions: List[Dict[str, Any]]) -> None:
        """
        从数据库加载持仓数据

        Args:
            positions: 持仓数据列表
        """
        self._positions.clear()
        for pos_data in positions:
            symbol = pos_data.get("symbol")
            if not symbol:
                continue
            position = StrategyPosition(
                strategy_id=self.strategy_id,
                symbol=symbol,
                account_id=pos_data.get("account_id"),
                pos_long_td=pos_data.get("pos_long_td", 0),
                pos_long_yd=pos_data.get("pos_long_yd", 0),
                pos_short_td=pos_data.get("pos_short_td", 0),
                pos_short_yd=pos_data.get("pos_short_yd", 0),
                avg_price_long=pos_data.get("avg_price_long", 0.0),
                avg_price_short=pos_data.get("avg_price_short", 0.0),
                position_profit=pos_data.get("position_profit", 0.0),
                close_profit=pos_data.get("close_profit", 0.0),
            )
            self._positions[symbol] = position
            logger.info(
                f"策略 [{self.strategy_id}] 加载持仓: {symbol} "
                f"多仓={position.pos_long}, 空仓={position.pos_short}"
            )

    def save_positions(self) -> None:
        """保存持仓到数据库"""
        if not self.strategy_manager:
            return
        for position in self._positions.values():
            if position.total_pos > 0:  # 只保存有持仓的记录
                self.strategy_manager.save_strategy_position(position)

    # ==================== Backward Compatibility Properties ====================

    @property
    def pos_long(self) -> int:
        """多头持仓（主合约）- 兼容旧接口"""
        pos = self._positions.get(self.symbol)
        return pos.pos_long if pos else 0

    @pos_long.setter
    def pos_long(self, value: int) -> None:
        """设置多头持仓（主合约）- 兼容旧接口"""
        pos = self._get_or_create_position(self.symbol)
        # 默认分配到昨仓
        pos.pos_long_yd = value
        pos.pos_long_td = 0

    @property
    def pos_short(self) -> int:
        """空头持仓（主合约）- 兼容旧接口"""
        pos = self._positions.get(self.symbol)
        return pos.pos_short if pos else 0

    @pos_short.setter
    def pos_short(self, value: int) -> None:
        """设置空头持仓（主合约）- 兼容旧接口"""
        pos = self._get_or_create_position(self.symbol)
        # 默认分配到昨仓
        pos.pos_short_yd = value
        pos.pos_short_td = 0

    @property
    def pos_price(self) -> float:
        """持仓均价（主合约多头）- 兼容旧接口"""
        pos = self._positions.get(self.symbol)
        return pos.avg_price_long if pos else 0.0

    @pos_price.setter
    def pos_price(self, value: float) -> None:
        """设置持仓均价（主合约）- 兼容旧接口"""
        pos = self._get_or_create_position(self.symbol)
        pos.avg_price_long = value
        pos.avg_price_short = value

    @property
    def close_profit(self) -> float:
        """平仓盈亏（主合约）- 兼容旧接口"""
        pos = self._positions.get(self.symbol)
        return pos.close_profit if pos else 0.0

    @close_profit.setter
    def close_profit(self, value: float) -> None:
        """设置平仓盈亏（主合约）- 兼容旧接口"""
        pos = self._get_or_create_position(self.symbol)
        pos.close_profit = value

    async def execute_signal(self) -> None:
        """执行信号（支持锁仓模式）"""
        if not self.signal or self.param is None:
            return

        signal = self.signal
        if signal.exit_time:
            # 平仓处理
            if self.param.lock_position:
                await self._handle_lock_close(signal)
            else:
                await self._handle_normal_close(signal)
        else:
            # 开仓处理
            if self.param.lock_position:
                await self._handle_lock_open(signal)
            else:
                await self._handle_normal_open(signal)

    async def _handle_normal_close(self, signal: Signal) -> None:
        """正常模式平仓处理"""
        if self._has_pending_open_cmd():
            # 有未完成的开仓操作，先撤单
            logger.info(f"策略 [{self.strategy_id}] 有未完成的开仓指令，先取消指令")
            await self._cancel_pending_cmds()
            return

        if self._has_pending_close_cmd():
            # 已有进行中的平仓指令
            return

        pos = self.pos_long if signal.side == 1 else self.pos_short
        if pos > 0:
            exit_cmd = OrderCmd(
                symbol=self.param.symbol,
                offset=Offset.CLOSE,
                direction=Direction.SELL if signal.side == 1 else Direction.BUY,
                volume=pos,
                price=0,
            )
            await self._send_order_cmds([exit_cmd])

    async def _handle_lock_close(self, signal: Signal) -> None:
        """锁仓模式平仓：反向开仓实现锁仓，不平今，保证净头寸为0"""
        if self._has_pending_cmd():
            # 已有进行中的平仓指令
            return

        pos_net = self.pos_long - self.pos_short
        if pos_net > 0:
            # 锁仓：净头寸为多，需要开空
            lock_cmd = OrderCmd(
                symbol=self.param.symbol,
                offset=Offset.OPEN,
                direction=Direction.SELL,
                volume=pos_net,
                price=0,
            )
            await self._send_order_cmds([lock_cmd])
        elif pos_net < 0:
            # 锁仓：净头寸为空，需要开多
            lock_cmd = OrderCmd(
                symbol=self.param.symbol,
                offset=Offset.OPEN,
                direction=Direction.BUY,
                volume=-pos_net,
                price=0,
            )
            await self._send_order_cmds([lock_cmd])

    async def _handle_normal_open(self, signal: Signal) -> None:
        """正常模式开仓处理"""
        if self._has_pending_cmd():
            return

        pos = self.pos_long if signal.side == 1 else self.pos_short
        if pos < self.volume:
            entry_cmd = OrderCmd(
                symbol=self.symbol,
                offset=Offset.OPEN,
                direction=Direction.BUY if signal.side == 1 else Direction.SELL,
                volume=self.volume - pos,
                price=0,
            )
            await self._send_order_cmds([entry_cmd])

    async def _handle_lock_open(self, signal: Signal) -> None:
        """锁仓模式开仓：先平反向昨仓，再开新仓"""
        if self._has_pending_cmd():
            return

        position = self.get_position(self.symbol)
        cmds: List[OrderCmd] = []    

        if signal.side == 1:
            pos_net = self.pos_long - self.pos_short
            if pos_net > self.volume:
                #净多超过目标手数了，优先平多(昨)，剩余开空
                target_volume = pos_net - self.volume
                pos_long_yd = min(position.pos_long_yd or 0,self.pos_long) if position else 0
                close_volume  = min(target_volume, pos_long_yd)
                open_volume = target_volume - close_volume
                logger.info(f"开多，净多头[{pos_net}]超过目标手数[{self.volume}]，优先平多(昨)[{close_volume}]手，剩余开空[{open_volume}]手")
                if close_volume >0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.CLOSE,
                            direction=Direction.SELL,
                            volume=close_volume,
                            price=0,
                        )
                    )
                if open_volume > 0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.OPEN,
                            direction=Direction.BUY,
                            volume=open_volume,
                            price=0,
                        )
                    )


            elif pos_net < self.volume:
                #净多不足目标手数了，优先平空(昨)，剩余开多
                target_volume = self.volume - pos_net
                pos_short_yd = min(position.pos_short_yd or 0,self.pos_short) if position else 0
                close_volume  = min(target_volume, pos_short_yd)
                open_volume = target_volume - close_volume
                logger.info(f"开多，净多头[{pos_net}]不足目标手数[{self.volume}]，优先平空(昨)[{close_volume}]手，剩余开多[{open_volume}]手")
                if close_volume >0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.CLOSE,
                            direction=Direction.BUY,
                            volume=close_volume,
                            price=0,
                        )
                    )
                if open_volume > 0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.OPEN,
                            direction=Direction.BUY,
                            volume=open_volume,
                            price=0,
                        )
                    )
        if signal.side == -1:
            pos_net = self.pos_short - self.pos_long
            if pos_net > self.volume:
                #净空超过目标手数了，优先平空(昨)，剩余开多
                target_volume = pos_net - self.volume
                pos_short_yd = min(position.pos_short_yd or 0,self.pos_short) if position else 0
                close_volume  = min(target_volume, pos_short_yd)
                open_volume = target_volume - close_volume
                logger.info(f"开空，净空头[{pos_net}]超过目标手数[{self.volume}]，优先平空(昨)[{close_volume}]手，剩余开多[{open_volume}]手")
                if close_volume >0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.CLOSE,
                            direction=Direction.BUY,
                            volume=close_volume,
                            price=0,
                        )
                    )
                if open_volume > 0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.OPEN,
                            direction=Direction.BUY,
                            volume=open_volume,
                            price=0,
                        )
                    )
            elif pos_net < self.volume:
                #净空不足目标手数了，优先平多(昨)，剩余开空
                target_volume = self.volume - pos_net
                pos_long_yd = min(position.pos_long_yd or 0,self.pos_long) if position else 0
                close_volume  = min(target_volume, pos_long_yd)
                open_volume = target_volume - close_volume
                logger.info(f"开空，净空头[{pos_net}]不足目标手数[{self.volume}]，优先平多(昨)[{close_volume}]手，剩余开空[{open_volume}]手")
                if close_volume >0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.CLOSE,
                            direction=Direction.SELL,
                            volume=close_volume,
                            price=0,
                        )
                    )
                if open_volume > 0:
                    cmds.append(
                        OrderCmd(
                            symbol=self.symbol,
                            offset=Offset.OPEN,
                            direction=Direction.SELL,
                            volume=open_volume,
                            price=0,
                        )
                    )

        if cmds and len(cmds) > 0:
            await self._send_order_cmds(cmds)

    def _on_cmd_change(self, cmd: OrderCmd):
        """处理订单状态变化（支持多指令和多合约持仓）"""
        if not cmd.is_finished:
            return

        # 等报单指令完成，指令中的成交数量不会变化了，再更新持仓
        if cmd.filled_volume > 0:
            # 获取或创建对应合约的持仓对象
            position = self._get_or_create_position(cmd.symbol)

            # 使用 StrategyPosition 的更新方法
            position.update_from_trade(
                direction=cmd.direction,
                offset=cmd.offset,
                volume=cmd.filled_volume,
                price=cmd.filled_price,
            )

            logger.info(
                f"策略 [{self.strategy_id}] {cmd.symbol} 持仓更新: "
                f"方向={cmd.direction.value}, 开平={cmd.offset.value}, "
                f"数量={cmd.filled_volume}, 价格={cmd.filled_price}, "
                f"当前持仓 多={position.pos_long}({position.pos_long_td}/{position.pos_long_yd}) "
                f"空={position.pos_short}({position.pos_short_td}/{position.pos_short_yd})"
            )

            # 保存到数据库
            self.save_positions()

        if cmd.finish_reason and "报单被拒" in cmd.finish_reason:
            if cmd.offset == Offset.OPEN:
                self.opening_paused = True
            elif cmd.offset == Offset.CLOSE:
                self.closing_paused = True

        # 从pending列表中移除完成的指令
        if cmd in self._pending_cmds:
            self._pending_cmds.remove(cmd)
        # 保存到历史
        self._hist_cmds[cmd.cmd_id] = cmd

    def get_trading_status(self) -> str:
        """是否正在交易中(开仓中，平仓中)"""
        open_count = sum(
            1 for cmd in self._pending_cmds if not cmd.is_finished and cmd.offset == Offset.OPEN
        )
        close_count = sum(
            1 for cmd in self._pending_cmds if not cmd.is_finished and cmd.offset == Offset.CLOSE
        )

        if open_count > 0:
            return f"开仓中({open_count})"
        if close_count > 0:
            return f"平仓中({close_count})"
        return ""

    def enable(self, status: bool = True) -> bool:
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
    async def _send_order_cmds(self, cmds: List[OrderCmd]):
        """发送报单指令（支持多指令）"""
        if self.param is None:
            logger.error(f"策略 [{self.strategy_id}] 的参数未初始化")
            return

        for cmd in cmds:
            if cmd.offset == Offset.CLOSE and self.closing_paused:
                logger.warning(f"策略 [{self.strategy_id}] 暂停平仓")
                continue
            if cmd.offset == Offset.OPEN and self.opening_paused:
                logger.warning(f"策略 [{self.strategy_id}] 暂停开仓")
                continue

            self._pending_cmds.append(cmd)
            self._hist_cmds[cmd.cmd_id] = cmd
            if cmd.on_change is None:
                cmd.on_change = self._on_cmd_change

            cmd.source = f"策略-{self.strategy_id}"
            cmd.order_timeout = self.param.order_timeout
            cmd.cmd_timeout = self.param.cmd_timeout
            cmd.volume_per_order = self.param.volume_per_order

            if self.strategy_manager is None:
                logger.error(f"策略 [{self.strategy_id}] 的 strategy_manager 未初始化")
                return
            await self.strategy_manager.send_order_cmd(self.strategy_id, cmd)

    async def _cancel_pending_cmds(self) -> None:
        """取消所有进行中的指令"""
        if self.strategy_manager is None:
            return
        for cmd in list(self._pending_cmds):
            if not cmd.is_finished:
                await self.strategy_manager.cancel_order_cmd(self.strategy_id, cmd)
        self._pending_cmds.clear()

    def _has_pending_cmd(self) -> bool:
        """是否有进行中的指令"""
        return any(not cmd.is_finished for cmd in self._pending_cmds)

    def _has_pending_open_cmd(self) -> bool:
        """是否有进行中的开仓指令"""
        return any(
            not cmd.is_finished and cmd.offset == Offset.OPEN for cmd in self._pending_cmds
        )

    def _has_pending_close_cmd(self) -> bool:
        """是否有进行中的平仓指令"""
        return any(
            not cmd.is_finished and cmd.offset == Offset.CLOSE for cmd in self._pending_cmds
        )

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
