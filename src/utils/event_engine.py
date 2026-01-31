"""
事件驱动引擎
"""

import asyncio
import inspect
from collections import defaultdict
from queue import Empty, Queue
from threading import Thread
from typing import Any, Callable

from src.utils.logger import logger


class EventTypes:
    """事件类型常量定义"""

    # 账户更新事件
    ACCOUNT_UPDATE = "e:account.update"
    # 账户状态事件
    ACCOUNT_STATUS = "e:account.status"
    # 持仓事件
    POSITION_UPDATE = "e:position.update"
    # 委托单事件
    ORDER_UPDATE = "e:order.update"
    # 成交事件
    TRADE_UPDATE = "e:trade.created"
    # 行情事件
    TICK_UPDATE = "e:tick.update"
    KLINE_UPDATE = "e:kline.update"
    # 系统告警
    SYSTEM_ERROR = "e:system.error"
    # 告警事件
    ALARM_UPDATE = "e:alarm.update"
    # 数据更新事件（通用）
    DATA_UPDATE = "e:data.update"


HandlerType = Callable[[Any], None]


class Event:
    """
    Event object consists of a type string which is used
    by event engine for distributing event, and a data
    object which contains the real data.
    """

    def __init__(self, type: str, data: Any = None) -> None:
        """"""
        self.type: str = type
        self.data: Any = data


class EventEngine:
    """
    独立事件引擎

    每个组件应该创建自己的EventEngine实例。

    功能：
    1. 事件分发：根据事件类型将事件分发给注册的处理器
    2. 线程安全：使用Queue和Thread实现线程安全的事件处理
    3. 通用处理器：支持注册处理所有事件的通用处理器
    """

    def __init__(self, name: str = "EventEngine") -> None:
        """
        初始化事件引擎

        Args:
            name: 事件引擎名称，用于日志区分
        """
        self._name = name
        self._queue: Queue = Queue()
        self._active: bool = False
        self._thread: Thread = Thread(target=self._run, daemon=True)
        self._handlers: defaultdict = defaultdict(list)
        self._general_handlers: list = []

    def _run(self) -> None:
        """
        事件处理主循环

        从队列中获取事件并处理，如果队列为空则等待1秒。
        """
        while self._active:
            try:
                event: Event = self._queue.get(block=True, timeout=1)
                self._process(event)
            except Empty:
                pass

    def _process(self, event: Event) -> None:
        """
        处理单个事件

        首先将事件分发给注册了该类型事件的所有处理器，
        然后将事件分发给所有通用处理器。

        Args:
            event: 要处理的事件
        """
        try:
            # 分发给特定类型的处理器
            if event.type in self._handlers:
                for handler in self._handlers[event.type]:
                    self._call_handler(handler, event)

            # 分发给通用处理器
            if self._general_handlers:
                for handler in self._general_handlers:
                    self._call_handler(handler, event)
        except Exception as e:
            logger.exception(f"[{self._name}] 事件处理异常: {e}")

    def _call_handler(self, handler: Callable, event: Event) -> None:
        """
        调用事件处理器，支持同步和异步处理器

        Args:
            handler: 处理器函数
            event: 事件对象
        """
        if inspect.iscoroutinefunction(handler):
            # 异步处理器：需要在事件循环中调度
            try:
                # 尝试获取主事件循环
                from src.app_context import get_app_context
                ctx = get_app_context()
                loop = ctx.get_event_loop()
                if loop and loop.is_running():
                    # 使用 run_coroutine_threadsafe 在线程中安全地调度协程
                    asyncio.run_coroutine_threadsafe(handler(event.data), loop)
                else:
                    logger.warning(f"[{self._name}] 事件循环未运行，无法处理异步处理器")
            except Exception as e:
                logger.error(f"[{self._name}] 调度异步处理器失败: {e}")
        else:
            # 同步处理器：直接调用
            handler(event.data)

    def start(self) -> None:
        """
        启动事件引擎

        启动事件处理线程。
        """
        if not self._active:
            self._active = True
            self._thread.start()
            logger.info(f"[{self._name}] 事件引擎已启动")

    def stop(self) -> None:
        """
        停止事件引擎

        停止事件处理线程并等待其结束。
        """
        self._active = False
        self._thread.join()
        logger.info(f"[{self._name}] 事件引擎已停止")

    def put(self, event_type: str, data: Any) -> None:
        """
        发送事件到队列

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        self._queue.put(Event(event_type, data))

    def register(self, event_type: str, handler: HandlerType) -> None:
        """
        注册事件处理器

        为特定事件类型注册处理器函数。

        Args:
            event_type: 事件类型
            handler: 处理器函数，接收事件数据作为参数
        """
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unregister(self, event_type: str, handler: HandlerType) -> None:
        """
        注销事件处理器

        Args:
            event_type: 事件类型
            handler: 处理器函数
        """
        handler_list: list = self._handlers[event_type]

        if handler in handler_list:
            handler_list.remove(handler)

        if not handler_list:
            self._handlers.pop(event_type)

    def register_general(self, handler: HandlerType) -> None:
        """
        注册通用事件处理器

        通用处理器会接收所有类型的事件。

        Args:
            handler: 处理器函数，接收事件数据作为参数
        """
        if handler not in self._general_handlers:
            self._general_handlers.append(handler)

    def unregister_general(self, handler: HandlerType) -> None:
        """
        注销通用事件处理器

        Args:
            handler: 处理器函数
        """
        if handler in self._general_handlers:
            self._general_handlers.remove(handler)
