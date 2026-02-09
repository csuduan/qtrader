"""
策略管理器（支持异步 TradingEngine）
负责策略实例化、启动/停止管理、事件路由、参数加载
"""

import asyncio
import csv
import os
from datetime import datetime,timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.app_context import get_app_context
from src.models.object import BarData, Direction, Exchange, Offset, TickData
from src.trader.core.trading_engine import TradingEngine
from src.trader.order_cmd import OrderCmd
from src.trader.strategy.base_strategy import BaseStrategy
from src.utils.bar_generator import MultiSymbolBarGenerator, parse_interval
from src.utils.config_loader import StrategyConfig
from src.utils.event_engine import EventEngine, EventTypes
from src.utils.logger import get_logger

ctx = get_app_context()


logger = get_logger(__name__)

# 全局CSV缓存：{csv_path: {strategy_id: params_dict}}
_csv_cache: Dict[str, Dict[str, dict]] = {}


def load_csv_file(csv_path: str) -> Dict[str, dict]:
    """加载CSV文件到缓存"""
    if csv_path in _csv_cache:
        return _csv_cache[csv_path]

    result = {}
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                strategy_id = row.get("strategy_id", "")
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


def load_strategy_params(config: StrategyConfig, strategy_id: str) -> dict:
    """
    加载策略参数

    Args:
        yaml_config: 从YAML加载的策略配置
        strategy_id: 策略ID

    Returns:
        dict: 合并后的策略参数
    """
    # 从YAML配置复制参数
    params = {}
    params_file = config.params_file
    if not params_file:
        return {}

    # 处理变量替换（如 {date} 替换为当前日期YYYYMMDD）
    today_str = datetime.now().strftime("%Y%m%d")
    params_file = params_file.replace("{date}", today_str)

    # 构建完整路径
    app_config = get_app_context().get_config()
    csv_path = os.path.join(app_config.paths.params, params_file)

    # 加载CSV参数
    csv_data = load_csv_file(csv_path)
    csv_params = csv_data.get(strategy_id, {})
    if not csv_params:
        return {}

    # CSV参数直接覆盖
    for key, value in csv_params.items():
        if value:
            params[key] = value
    config.params = params
    return params


class StrategyManager:
    """策略管理器"""

    def __init__(self, strategies_config: Dict[str, StrategyConfig], trading_engine: TradingEngine):
        self.strategies_configs: Dict[str, StrategyConfig] = strategies_config
        self.strategies: Dict[str, BaseStrategy] = {}
        self.trading_engine: TradingEngine = trading_engine
        self.subscribed_symbols: set = set()
        # 订单ID -> 策略ID 的映射关系
        self.order_strategy_map: Dict[str, str] = {}
        # cmd_id -> 策略ID 的映射关系
        self.event_engine: Optional[EventEngine] = None

        # Bar生成器管理器 (symbol -> BarGenerator)
        self._bar_generators: Dict[str, MultiSymbolBarGenerator] = {}
        # 策略bar订阅映射 (symbol -> {strategy_id -> [interval_str]})
        self._strategy_bar_subscriptions: Dict[str, Dict[str, List[str]]] = {}

    async def start(self) -> bool:
        """
        启动策略管理器

        Returns:
            bool: 初始化是否成功
        """
        try:
            self.event_engine = ctx.get_event_engine()
            # 加载并实例化策略
            await self._load_strategies()
            # 注册事件到 EventEngine
            self._register_events()
            # 启动所有策略
            self.start_all()
            logger.info("策略管理器初始化完成")
            return True

        except Exception as e:
            logger.exception(f"策略管理器初始化失败: {e}")
            return False

    async def _load_strategies(self) -> None:
        """从配置加载并实例化策略"""
        from src.trader.strategy import get_strategy_class

        for name, config in self.strategies_configs.items():
            if not config.enabled:
                logger.info(f"策略 {name} 未启用，跳过")
                continue

            strategy_type = config.type
            strategy_class = get_strategy_class(strategy_type)
            if strategy_class is None:
                logger.warning(f"未找到策略类: {strategy_type}")
                continue

            # 加载参数（YAML默认参数 + CSV覆盖）
            load_strategy_params(config, name)

            # 创建策略实例
            try:
                strategy:BaseStrategy = strategy_class(name, config)
                strategy.strategy_manager = self
                self.strategies[name] = strategy
                strategy.init(self.trading_engine.trading_day)
                logger.info(f"添加策略: {name}")

                # 按需订阅合约行情
                symbol = strategy.symbol
                if symbol:
                    await self.subscribe_symbol(symbol, config.bar)
                    strategy.bar_subscriptions.append(f"{symbol}-{config.bar}")
                    # 如果策略需要bar，初始化BarGenerator订阅
                    # if config.bar:
                    #     try:
                    #         self._setup_bar_generator(name, symbol, [config.bar])
                    #     except ValueError:
                    #         logger.warning(f"策略 {name} 配置的交易所无效: {exchange_str}")
            except Exception as e:
                logger.exception(f"创建策略 {name} 失败: {e}", exc_info=True)

    def _register_events(self) -> None:
        """注册策略事件到 EventEngine"""
        if not self.event_engine:
            logger.warning("EventEngine 未设置，跳过事件注册")
            return

        # 行情事件 - 分发给所有活跃策略
        async def _on_tick(data):
            await self._dispatch_market_event("on_tick", data)
        async def _on_bar(data):
            await self._dispatch_market_event("on_bar", data)
        async def _on_order(data):
            await self._dispatch_order_event("on_order", data)
        async def _on_trade(data):
            await self._dispatch_order_event("on_trade", data)

        self.event_engine.register(EventTypes.TICK_UPDATE, _on_tick)
        self.event_engine.register(EventTypes.KLINE_UPDATE, _on_bar)
        # 订单/成交事件 - 分发给对应策略
        self.event_engine.register( EventTypes.ORDER_UPDATE, _on_order)
        self.event_engine.register(EventTypes.TRADE_UPDATE, _on_trade)

        logger.info("策略事件已注册到EventEngine")

    def _extract_order_id(self, data: Any) -> Optional[str]:
        """从数据中提取订单ID"""
        if isinstance(data, dict):
            return data.get("order_id")
        elif hasattr(data, "order_id"):
            return data.order_id
        return None

    async def _dispatch_market_event(self, method: str, data: Any) -> None:
        """
        分发行情事件到所有活跃策略

        Args:
            method: 策略方法名
            data: 事件数据
        """
        # 如果是tick事件，更新BarGenerator
        # if method == "on_tick" and hasattr(data, "symbol"):
        #    self._update_bar_generator(data)

        if method == "on_bar" and hasattr(data, "symbol"):
            bar: BarData = data
            for name, strategy in self.strategies.items():
                if strategy.enabled and bar.id in strategy.bar_subscriptions:
                    try:
                        await strategy.on_bar(bar)
                    except Exception as e:
                        logger.exception(f"策略 {name} {method} 失败: {e}")

        if method == "on_tick" and hasattr(data, "symbol"):
            tick: TickData = data
            for name, strategy in self.strategies.items():
                if strategy.enabled:
                    try:
                        await strategy.on_tick(tick)
                    except Exception as e:
                        logger.exception(f"策略 {name} {method} 失败: {e}")


    def _dispatch_order_event(self, method: str, data: Any) -> None:
        """
        分发订单/成交事件到对应策略

        Args:
            method: 策略方法名
            data: 事件数据
        """
        order_id = self._extract_order_id(data)
        if not order_id:
            return

        strategy_id = self.order_strategy_map.get(order_id)
        if not strategy_id or strategy_id not in self.strategies:
            return

        strategy = self.strategies[strategy_id]
        if strategy.enabled:
            try:
                getattr(strategy, method)(data)
            except Exception as e:
                logger.exception(f"策略 {strategy_id} {method} 失败: {e}")


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

    def start_all(self) -> None:
        """启动所有已启用的策略"""
        for strategy in self.strategies.values():
            if strategy.enabled:
                strategy.start()

    def stop_all(self) -> None:
        """停止所有策略"""
        for strategy in self.strategies.values():
            strategy.stop()

    def reset_all_for_new_day(self) -> None:
        """重置所有策略（开盘前调用）"""
        trading_day = self.trading_engine.trading_day
        for strategy in self.strategies.values():
            if hasattr(strategy, "reset_for_new_day"):
                strategy.init(trading_day)
        logger.info("所有策略已重置")

    async def subscribe_symbol(self, symbol: str, interval: str) -> bool:
        """订阅合约行情（按需订阅）"""
        if not self.trading_engine:
            return False
        await self.trading_engine.subscribe_symbol(symbol)
        if interval:
            await self.trading_engine.subscribe_bars(symbol, interval)
        return True

    def get_status(self) -> list:
        """获取所有策略状态"""

        def _get_trading_status(signal: dict) -> str:
            """根据信号获取交易状态"""
            if not signal or signal.get("side") == 0:
                return "无"
            if signal.get("exit_order_id"):
                return "平仓中"
            if signal.get("entry_order_id"):
                return "开仓中"
            return "持仓"

        return [
            {
                "strategy_id": s.strategy_id,
                "enabled": s.enabled,
                "inited": s.inited,
                "config": s.config.model_dump(),
                "params": s.get_params(),  # 保留向后兼容
                "base_params": s.get_params().get("base", []),
                "ext_params": s.get_params().get("ext", []),
                "signal": s.get_signal() if hasattr(s, "get_signal") else {},
                "trading_status": _get_trading_status(
                    s.get_signal() if hasattr(s, "get_signal") else {}
                ),
            }
            for s in self.strategies.values()
        ]

    # ==================== 交易接口 ====================

    async def _insert_order(
        self,
        strategy_id: str,
        symbol: str,
        direction: Direction,
        volume: int,
        price: Optional[float],
        offset: Offset,
    ) -> Optional[str]:
        """
        插入订单通用方法（异步版本）

        Args:
            strategy_id: 策略ID
            symbol: 合约代码
            direction: 方向
            volume: 手数
            price: 价格（None为市价）
            offset: 开平标识

        Returns:
            委托单ID
        """
        if not self.trading_engine:
            logger.warning(f"TradingEngine 未设置，无法执行下单")
            return None

        try:
            order_id = await self.trading_engine.insert_order(
                symbol=symbol,
                direction=direction.value,
                offset=offset.value,
                volume=volume,
                price=price or 0,
            )
            if order_id:
                # 记录订单与策略的映射关系
                self.order_strategy_map[order_id] = strategy_id
                logger.info(
                    f"策略 [{strategy_id}] {direction.value} {volume}手 @{price or '市价'} -> 订单ID: {order_id}"
                )
            return order_id
        except Exception as e:
            logger.error(f"策略 [{strategy_id}] 下单失败: {e}")
            return None

    async def send_order_cmd(self, strategy_id: str, order_cmd: OrderCmd) -> None:
        """
        发送订单指令 - 通过 TradingEngine

        Args:
            strategy_id: 策略ID
            order_cmd: 订单指令对象
        """
        try:
            await self.trading_engine.insert_order_cmd(order_cmd)
            logger.info(f"策略 [{strategy_id}] 发送订单指令: {order_cmd}")
        except Exception as e:
            logger.exception(f"策略 [{strategy_id}] 发送订单指令失败: {e}")

    async def cancel_order_cmd(self, strategy_id: str, order_cmd: OrderCmd) -> None:
        """
        取消订单指令 - 通过 TradingEngine

        Args:
            strategy_id: 策略ID
            order_cmd: 订单指令对象
        """
        try:
            await self.trading_engine.cancel_order_cmd(order_cmd.cmd_id)
            logger.info(f"策略 [{strategy_id}] 取消订单指令: {order_cmd}")
        except Exception as e:
            logger.error(f"策略 [{strategy_id}] 取消订单指令失败: {e}")

    def get_position(self, symbol: str) -> Optional["PositionData"]:
        """
        获取指定合约的持仓信息

        Args:
            symbol: 合约代码

        Returns:
            PositionData: 持仓数据，如果不存在则返回None
        """
        from src.models.object import PositionData

        if self.trading_engine and self.trading_engine.positions:
            # 先直接用 symbol 查找
            pos = self.trading_engine.positions.get(symbol)
            if pos:
                return pos
            # 如果没找到，尝试遍历所有持仓（可能 symbol 格式不一致）
            for p in self.trading_engine.positions.values():
                if p.symbol == symbol:
                    return p
        return None

    def open(
        self,
        strategy_id: str,
        symbol: str,
        direction: str,
        volume: int,
        price: Optional[float] = None,
    ) -> Optional[str]:
        """
        开仓 - 通过 TradingEngine

        Args:
            strategy_id: 策略ID
            symbol: 合约代码
            direction: 方向 ("BUY" 多开 / "SELL" 空开)
            volume: 手数
            price: 价格（None为市价）

        Returns:
            委托单ID
        """
        dir_enum = Direction.BUY if direction.upper() == "BUY" else Direction.SELL
        return self._insert_order(strategy_id, symbol, dir_enum, volume, price, Offset.OPEN)

    def close(
        self,
        strategy_id: str,
        symbol: str,
        direction: str,
        volume: int,
        price: Optional[float] = None,
    ) -> Optional[str]:
        """
        平仓 - 通过 TradingEngine

        Args:
            strategy_id: 策略ID
            symbol: 合约代码
            direction: 方向 ("BUY" 多平 / "SELL" 空平)
            volume: 手数
            price: 价格（None为市价）

        Returns:
            委托单ID
        """
        dir_enum = Direction.BUY if direction.upper() == "BUY" else Direction.SELL
        return self._insert_order(strategy_id, symbol, dir_enum, volume, price, Offset.CLOSE)

    async def cancel_order(self, strategy_id: str, order_id: str) -> bool:
        """
        撤单 - 通过 TradingEngine（异步版本）

        Args:
            strategy_id: 策略ID
            order_id: 订单ID

        Returns:
            是否成功
        """
        if not self.trading_engine:
            logger.warning(f"TradingEngine 未设置，无法执行撤单")
            return False

        # 验证订单是否属于该策略
        mapped_strategy_id = self.order_strategy_map.get(order_id)
        if mapped_strategy_id and mapped_strategy_id != strategy_id:
            logger.warning(
                f"订单 {order_id} 属于策略 {mapped_strategy_id}，策略 {strategy_id} 无法撤销"
            )
            return False

        try:
            success = await self.trading_engine.cancel_order(order_id)
            if success:
                logger.info(f"策略 [{strategy_id}] 撤单成功: {order_id}")
            return success
        except Exception as e:
            logger.error(f"策略 [{strategy_id}] 撤单失败: {e}")
            return False

    def cleanup_order_mapping(self, order_id: str) -> None:
        """清理订单映射（订单完成或取消后调用）"""
        self.order_strategy_map.pop(order_id, None)

    # ==================== Bar生成器管理 ====================

    def _setup_bar_generator(self, strategy_id: str, symbol: str, bar_intervals: list) -> None:
        """
        为策略设置BarGenerator订阅

        Args:
            strategy_id: 策略ID
            symbol: 合约代码
            exchange: 交易所
            bar_intervals: bar周期列表，如 ["M1", "M5", "M15"]
        """
        from src.utils.bar_generator import parse_interval

        # 获取或创建该symbol的BarGenerator
        if symbol not in self._bar_generators:
            self._bar_generators[symbol] = MultiSymbolBarGenerator()

        multi_gen = self._bar_generators[symbol]
        bar_gen = multi_gen.get_or_create(symbol)

        # 订阅需要的bar周期
        for interval_str in bar_intervals:
            if not parse_interval(interval_str):
                logger.warning(f"策略 {strategy_id} 配置了不支持的bar周期: {interval_str}")
                continue

            # 注册bar回调
            bar_gen.subscribe(
                interval_str, lambda bar, sid=strategy_id: self._on_bar_completed(sid, bar)
            )

            # 记录策略订阅
            if symbol not in self._strategy_bar_subscriptions:
                self._strategy_bar_subscriptions[symbol] = {}
            if strategy_id not in self._strategy_bar_subscriptions[symbol]:
                self._strategy_bar_subscriptions[symbol][strategy_id] = []
            if interval_str not in self._strategy_bar_subscriptions[symbol][strategy_id]:
                self._strategy_bar_subscriptions[symbol][strategy_id].append(interval_str)

            logger.debug(f"策略 {strategy_id} 订阅 {symbol} 的 {interval_str} bar")

    def _on_bar_completed(self, strategy_id: str, bar: BarData) -> None:
        """
        Bar生成完成时的回调

        Args:
            strategy_id: 策略ID
            bar: 完成的BarData
        """
        strategy = self.strategies.get(strategy_id)
        if not strategy or not strategy.enabled:
            return

        try:
            strategy.on_bar(bar)
        except Exception as e:
            logger.exception(f"策略 {strategy_id} on_bar 失败: {e}")

    def update_tick_for_bar(self, tick) -> None:
        """
        更新tick数据到BarGenerator
        应在收到tick时调用

        Args:
            tick: TickData
        """
        symbol = tick.symbol

        # 查找该symbol的BarGenerator
        multi_gen = self._bar_generators.get(symbol)
        if not multi_gen:
            return

        # 更新tick
        results = multi_gen.update_tick(tick)

        # 完成的bar已通过回调分发给策略
        # 这里可以记录日志或做其他处理
        if results:
            for std_symbol, bars in results.items():
                for bar in bars:
                    logger.debug(f"Bar完成: {std_symbol} {bar.interval.value} {bar.datetime}")

    def remove_bar_generator(self, symbol: str, exchange: Exchange) -> bool:
        """
        移除BarGenerator

        Args:
            symbol: 合约代码
            exchange: 交易所

        Returns:
            是否成功移除
        """
        if symbol in self._bar_generators:
            multi_gen = self._bar_generators[symbol]
            result = multi_gen.remove(symbol, exchange)
            if result:
                # 清理订阅记录
                self._strategy_bar_subscriptions.pop(symbol, None)
                # 如果没有其他合约，清理整个multi_gen
                if not multi_gen._generators:
                    del self._bar_generators[symbol]
                return True
        return False

    async def replay_strategy(self, strategy: BaseStrategy) -> bool:
        """
        回播当日策略行情
        流程：
        1. 暂停策略交易，暂停接收实时tick、bar推送
        2. 执行策略初始化方法
        3. 从网关获取kline
        4. 从kline中选出当前交易日的bar(按时间排序)
        5. 循环调用on_bar()
        6. 恢复策略交易，接收实时tick、bar推送

        Args:
            strategy_id: 策略ID

        Returns:
            bool: 回播是否成功
        """
        from datetime import datetime, timedelta

        strategy_id = strategy.strategy_id
        logger.info(f"策略 [{strategy_id}] 开始回播流程")

        # 获取当前交易日期
        trading_date = self.trading_engine.trading_day
        try:
            # 1. 暂停策略
            strategy.stop()
            # 2. 执行策略初始化方法
            strategy.init(trading_date)
            logger.info(f"策略 [{strategy_id}] 初始化完成")

            # 3. 从网关获取kline
            # 获取策略订阅的合约和周期
            if len(strategy.bar_subscriptions) == 0:
                logger.error(f"策略 [{strategy_id}] 未配置bar订阅")
                return False

            symbol, interval = strategy.bar_subscriptions[0].split("-")
            trading_bars = self.load_hist_bars(symbol, interval, trading_date,trading_date+timedelta(days=1))
            if not trading_bars:
                logger.error(f"策略 [{strategy_id}] 未获取到 {symbol} {interval} 的历史K线数据")
                return False
            
            # 4. 循环调用on_bar()
            for bar in trading_bars:
                await strategy.on_bar(bar)

            logger.info(f"策略 [{strategy_id}] K线回播完成")

            return True

        except Exception as e:
            logger.exception(f"策略 [{strategy_id}] 回播失败: {e}")
            return False

        finally:
            # 6. 恢复策略交易
            strategy.start()
            logger.info(f"策略 [{strategy_id}] 已恢复交易")
    

    async def replay_all_strategies(self) -> dict:
        """
        回播所有有效策略行情

        对所有启用的策略执行回播操作，用于系统启动后或每日开盘后
        将历史K线数据回播给策略，使其能够建立技术指标等状态

        Returns:
            dict: {"success": bool, "replayed_count": int, "message": str}
        """
        from datetime import datetime, timedelta

        logger.info("开始回播所有有效策略")

        if not self.trading_engine or not self.trading_engine.gateway:
            logger.error("网关未连接，无法回播策略")
            return {"success": False, "message": "网关未连接", "replayed_count": 0}

        gateway = self.trading_engine.gateway
        if not hasattr(gateway, "_klines"):
            logger.error("网关不支持获取K线数据")
            return {"success": False, "message": "网关不支持K线数据", "replayed_count": 0}

        # 1. 暂停交易
        self.trading_engine.pause()
        try:
            replayed_count = 0
            # 2. 对每个策略执行回播
            for _, strategy in self.strategies.items():
                ret = await self.replay_strategy(strategy)
                if ret:
                    replayed_count += 1
            logger.info(f"所有策略回播完成，成功回播 {replayed_count} 个策略")

            return {
                "success": True,
                "replayed_count": replayed_count,
                "message": f"成功回播 {replayed_count} 个策略",
            }

        except Exception as e:
            logger.exception(f"回播所有策略失败: {e}")
            return {"success": False, "message": f"回播失败: {str(e)}", "replayed_count": 0}
        finally:
            # 3. 恢复交易
            self.trading_engine.resume()
    
    def load_hist_bars(self,symbol, interval, start: datetime,end: datetime) ->List[BarData]:
        # 通过网关获取K线数据
        kline_df = self.trading_engine.get_kline(symbol, interval)
        if kline_df is None:
            logger.warning(f"未找到 {symbol} {interval} 的历史K线数据")
            return []

        # 筛选当前交易日的bar (K线时间戳是纳秒级)
        trading_bars = []
        for _, row in kline_df.iterrows():
            bar_datetime = row["datetime"]
            if bar_datetime >= start and bar_datetime <= end:
                bar = BarData(
                    symbol=symbol,
                    interval=interval,
                    datetime=bar_datetime,
                    open_price=float(row["open"]),
                    high_price=float(row["high"]),
                    low_price=float(row["low"]),
                    close_price=float(row["close"]),
                    volume=float(row["volume"]),
                    type="history",
                    update_time=bar_datetime+timedelta(minutes=1),
                )
                trading_bars.append(bar)
        if not trading_bars:
            logger.warning(f"未找到 {symbol} {interval} 从 {start} 开始的K线数据")
            return []

        # 按时间排序
        trading_bars.sort(key=lambda x: x.datetime)
        return trading_bars

    def get_strategy_bars(self, strategy_id: str, interval_str: str, count: int = 100):
        """
        获取策略的bar历史

        Args:
            strategy_id: 策略ID
            interval_str: 周期字符串
            count: 获取数量

        Returns:
            BarData列表
        """
        strategy = self.strategies.get(strategy_id)
        if not strategy:
            return []

        # 找到策略订阅的symbol
        for symbol, subscriptions in self._strategy_bar_subscriptions.items():
            if strategy_id in subscriptions:
                multi_gen = self._bar_generators.get(symbol)
                if multi_gen:
                    bar_gen = multi_gen.get(strategy.symbol, Exchange(strategy.exchange))
                    if bar_gen:
                        return bar_gen.get_bars(interval_str, count)
        return []
