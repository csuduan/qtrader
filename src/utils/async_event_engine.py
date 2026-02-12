"""
异步事件驱动引擎
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class Event:
    """
    Event object consists of a type string which is used
    by event engine for distributing event, and a data
    object which contains the real data.
    """

    def __init__(self, type: str, data: Any = None) -> None:
        self.type: str = type
        self.data: Any = data


HandlerType = Callable[[Any], None] | Callable[[Any], Awaitable[None]]


class AsyncEventEngine:
    """
    异步事件引擎

    功能：
    1. 事件分发：根据事件类型将事件分发给注册的处理器
    2. 异步支持：处理器可以是async或sync函数
    3. 并发处理：同一事件类型的处理器并发执行
    4. 通用处理器：支持注册处理所有事件的通用处理器
    """

    def __init__(self, name: str = "AsyncEventEngine") -> None:
        """
        初始化异步事件引擎

        Args:
            name: 事件引擎名称，用于日志区分
        """
        self._name = name
        self._running = False
        self._queue: asyncio.Queue = asyncio.Queue()
        self._handlers: defaultdict = defaultdict(list)
        self._general_handlers: list = []
        self._process_task: Optional[asyncio.Task] = None

    async def _process(self, event: Event) -> None:
        """
        处理单个事件

        首先将事件分发给注册了该类型事件的所有处理器，
        然后将事件分发给所有通用处理器。

        Args:
            event: 要处理的事件
        """
        try:
            # 分发给特定类型的处理器（并发执行）
            if event.type in self._handlers:
                tasks = []
                for handler in self._handlers[event.type]:
                    if asyncio.iscoroutinefunction(handler):
                        tasks.append(asyncio.create_task(handler(event.data)))
                    else:
                        # 同步处理器直接调用
                        try:
                            handler(event.data)
                        except Exception as e:
                            logger.exception(f"[{self._name}] 同步处理器执行失败: {e}")

                if tasks:
                    # 等待所有异步任务完成
                    await asyncio.gather(*tasks, return_exceptions=True)

            # 分发给通用处理器（并发执行）
            if self._general_handlers:
                tasks = []
                for handler in self._general_handlers:
                    if asyncio.iscoroutinefunction(handler):
                        tasks.append(asyncio.create_task(handler(event.data)))
                    else:
                        try:
                            handler(event.data)
                        except Exception as e:
                            logger.exception(f"[{self._name}] 同步处理器执行失败: {e}")

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.exception(f"[{self._name}] 事件处理异常: {e}")

    async def _run(self) -> None:
        """
        事件处理主循环

        从队列中获取事件并处理。
        """
        while self._running:
            try:
                event = await self._queue.get()
                await self._process(event)
            except asyncio.CancelledError:
                logger.info(f"[{self._name}] 事件循环被取消")
                break
            except Exception as e:
                logger.exception(f"[{self._name}] 事件循环错误: {e}")
                # 短暂休眠后继续
                await asyncio.sleep(0.1)

    def start(self) -> None:
        """
        启动事件引擎

        创建后台任务来处理事件。
        """
        if not self._running:
            self._running = True
            # 在当前运行的事件循环中创建任务
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # 没有运行的事件循环，需要手动创建
                logger.warning(f"[{self._name}] 没有运行的事件循环，无法启动")
                return

            self._process_task = asyncio.create_task(self._run())
            logger.info(f"[{self._name}] 异步事件引擎已启动")

    async def stop(self) -> None:
        """
        停止事件引擎

        停止事件处理并等待所有任务完成。
        """
        if not self._running:
            return

        self._running = False

        # 取消处理任务
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass

        logger.info(f"[{self._name}] 异步事件引擎已停止")

    def put(self, event_type: str, data: Any) -> None:
        """
        发送事件到队列

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if not self._running:
            logger.warning(f"[{self._name}] 事件引擎未运行，丢弃事件: {event_type}")
            return

        try:
            self._queue.put_nowait(Event(event_type, data))
        except asyncio.QueueFull:
            logger.error(f"[{self._name}] 事件队列已满，丢弃事件: {event_type}")
        except Exception as e:
            logger.error(f"[{self._name}] 发送事件失败: {e}")

    async def put_async(self, event_type: str, data: Any) -> None:
        """
        异步发送事件到队列

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if not self._running:
            logger.warning(f"[{self._name}] 事件引擎未运行，丢弃事件: {event_type}")
            return

        await self._queue.put(Event(event_type, data))

    def register(self, event_type: str, handler: HandlerType) -> None:
        """
        注册事件处理器

        为特定事件类型注册处理器函数。
        处理器可以是同步或异步函数。

        Args:
            event_type: 事件类型
            handler: 处理器函数，接收事件数据作为参数
        """
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug(f"[{self._name}] 注册事件处理器: {event_type}")

    def unregister(self, event_type: str, handler: HandlerType) -> None:
        """
        注销事件处理器

        Args:
            event_type: 事件类型
            handler: 处理器函数
        """
        handler_list = self._handlers[event_type]

        if handler in handler_list:
            handler_list.remove(handler)

        if not handler_list:
            self._handlers.pop(event_type)

    def register_general(self, handler: HandlerType) -> None:
        """
        注册通用事件处理器

        通用处理器会接收所有类型的事件。
        处理器可以是同步或异步函数。

        Args:
            handler: 处理器函数，接收事件数据作为参数
        """
        if handler not in self._general_handlers:
            self._general_handlers.append(handler)
            logger.debug(f"[{self._name}] 注册通用事件处理器")

    def unregister_general(self, handler: HandlerType) -> None:
        """
        注销通用事件处理器

        Args:
            handler: 处理器函数
        """
        if handler in self._general_handlers:
            self._general_handlers.remove(handler)

    @property
    def running(self) -> bool:
        """检查事件引擎是否运行"""
        return self._running

    def clear(self) -> None:
        """清空所有处理器"""
        self._handlers.clear()
        self._general_handlers.clear()
        logger.debug(f"[{self._name}] 已清空所有处理器")
