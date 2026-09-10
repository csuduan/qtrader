"""
异步事件驱动引擎
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class EventTypes:
    """事件类型常量定义"""

    # 账户更新事件
    ACCOUNT_UPDATE = "e:account.update"
    # 账户就绪通知事件
    ACCOUNT_READY = "e:account.ready"
    # 持仓事件
    POSITION_UPDATE = "e:position.update"
    # 委托单事件
    ORDER_UPDATE = "e:order.update"
    # 成交事件
    TRADE_UPDATE = "e:trade.created"
    # 行情事件
    TICK_UPDATE = "e:tick.update"
    TICK_BATCH_UPDATE = "e:tick.batch_update"
    KLINE_UPDATE = "e:kline.update"
    # 合约更新事件
    CONTRACT_UPDATE = "e:contract.update"
    # 系统告警
    SYSTEM_ERROR = "e:system.error"
    # 告警事件
    ALARM_UPDATE = "e:alarm.update"
    # 数据更新事件（通用）
    DATA_UPDATE = "e:data.update"
    # 报单指令更新事件
    ORDER_CMD_UPDATE = "e:order_cmd.update"


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
    5. 线程安全：支持其他线程通过put/put_async安全投递事件
    6. 双队列：关键事件（订单/成交/持仓/指令）不丢不延迟，普通事件（行情等）满时丢旧保新鲜
    """

    # 关键事件：丢失会导致持仓/订单状态错误，入关键队列，满了排队等待绝不丢弃
    CRITICAL_EVENT_TYPES = frozenset(
        {
            EventTypes.ORDER_UPDATE,
            EventTypes.TRADE_UPDATE,
            EventTypes.ORDER_CMD_UPDATE,
            EventTypes.POSITION_UPDATE,
            EventTypes.ACCOUNT_READY,
            EventTypes.SYSTEM_ERROR,
        }
    )

    def __init__(
        self,
        name: str = "AsyncEventEngine",
        queue_size: int = 10000,
        critical_queue_size: int = 50000,
    ) -> None:
        """
        初始化异步事件引擎

        Args:
            name: 事件引擎名称，用于日志区分
            queue_size: 普通队列上限（行情等，满后丢弃最旧事件保新鲜）
            critical_queue_size: 关键队列上限（订单/成交等，满后投递方协作等待，不丢弃）
        """
        self._name = name
        self._running = False
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._critical_queue: asyncio.Queue = asyncio.Queue(maxsize=critical_queue_size)
        self._drop_count = 0
        self._handlers: defaultdict = defaultdict(list)
        self._general_handlers: list = []
        self._process_tasks: list[asyncio.Task] = []
        self._process_lock = asyncio.Lock()
        self._pending_puts: set[asyncio.Task] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _dispatch(self, handlers: list, data: Any) -> None:
        """
        并发执行处理器

        同步处理器直接调用；异步处理器gather后逐个检查结果，
        异常不再被静默吞掉而是记录日志。

        Args:
            handlers: 处理器列表
            data: 事件数据
        """
        tasks = []
        async_handlers = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(asyncio.create_task(handler(data)))
                async_handlers.append(handler)
            else:
                try:
                    handler(data)
                except Exception as e:
                    logger.exception(f"[{self._name}] 同步处理器执行失败: {e}")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for handler, result in zip(async_handlers, results):
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    logger.error(
                        f"[{self._name}] 异步处理器执行失败 "
                        f"[{getattr(handler, '__qualname__', handler)}]: {result}",
                        exc_info=result,
                    )

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
                await self._dispatch(self._handlers[event.type], event.data)

            # 分发给通用处理器（并发执行）
            if self._general_handlers:
                await self._dispatch(self._general_handlers, event.data)

        except Exception as e:
            logger.exception(f"[{self._name}] 事件处理异常: {e}")

    async def _run(self, queue: asyncio.Queue) -> None:
        """
        事件消费循环

        从指定队列获取事件并处理。处理全程持有 _process_lock，
        保证事件串行处理（与单队列时代语义一致）；
        关键队列的消费者不被普通队列的积压拖住，实现关键事件优先消化。

        Args:
            queue: 要消费的事件队列
        """
        while self._running:
            try:
                event = await queue.get()
                async with self._process_lock:
                    await self._process(event)
                if queue is self._queue:
                    # 普通队列消费者处理完让出控制权：
                    # 同步处理器不 yield，连续消化积压时会独占处理锁饿死关键消费者
                    await asyncio.sleep(0)
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

            self._loop = loop
            # 两个消费任务：分别消费普通队列与关键队列
            self._process_tasks = [
                asyncio.create_task(self._run(self._queue)),
                asyncio.create_task(self._run(self._critical_queue)),
            ]
            logger.info(f"[{self._name}] 异步事件引擎已启动")

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """
        停止事件引擎

        先限时排空队列中残留事件（避免事件丢失），再取消处理任务。

        Args:
            drain_timeout: 排空队列的超时时间（秒）
        """
        if not self._running:
            return

        self._running = False

        # 排空队列中残留事件
        try:
            await asyncio.wait_for(self._drain(), timeout=drain_timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[{self._name}] 排空事件队列超时，放弃剩余事件")

        # 取消处理任务
        for task in self._process_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._process_tasks = []

        # 取消仍在等待队列空位的投递任务
        if self._pending_puts:
            for task in self._pending_puts:
                task.cancel()
            await asyncio.gather(*self._pending_puts, return_exceptions=True)
            self._pending_puts.clear()

        self._loop = None
        logger.info(f"[{self._name}] 异步事件引擎已停止")

    async def _drain(self) -> None:
        """处理队列中所有残留事件（由 stop 在 _running=False 后调用），关键队列优先"""
        while True:
            try:
                event = self._critical_queue.get_nowait()
            except asyncio.QueueEmpty:
                try:
                    event = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            await self._process(event)

    def put(self, event_type: str, data: Any) -> None:
        """
        发送事件到队列，支持跨线程安全调用

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if not self._running or self._loop is None:
            logger.warning(f"[{self._name}] 事件引擎未运行，丢弃事件: {event_type}")
            return

        event = Event(event_type, data)

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is self._loop:
            # 同一线程：直接操作
            self._safe_put(event)
        else:
            # 其他线程：通过 call_soon_threadsafe 安全投递
            self._loop.call_soon_threadsafe(self._safe_put, event)

    def _safe_put(self, event: Event) -> None:
        """非阻塞投递事件

        按事件类型分流到两个队列，满队时行为不同：
        - 普通事件（行情等）：丢弃队首最旧事件以容纳新事件（保新鲜）
        - 关键事件（订单/成交等）：调度协作式等待任务排队入队，绝不丢弃
          （网关回调线程经 call_soon_threadsafe 进来后立即返回，线程不阻塞）
        日志按频率采样避免刷屏。
        """
        if event.type in self.CRITICAL_EVENT_TYPES:
            queue = self._critical_queue
        else:
            queue = self._queue

        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            if queue is self._critical_queue:
                # 关键队列满：创建任务协作等待空位，事件不丢
                task = asyncio.create_task(queue.put(event))
                self._pending_puts.add(task)
                task.add_done_callback(self._pending_puts.discard)
                self._drop_count += 1
                if self._drop_count == 1 or self._drop_count % 100 == 0:
                    logger.warning(
                        f"[{self._name}] 关键事件队列已满，事件排队等待 "
                        f"（累计 {self._drop_count} 次，最近: {event.type}）"
                    )
            else:
                try:
                    queue.get_nowait()  # 丢弃最旧
                    queue.put_nowait(event)
                    self._drop_count += 1
                    if self._drop_count == 1 or self._drop_count % 100 == 0:
                        logger.warning(
                            f"[{self._name}] 行情事件队列已满，丢弃最旧事件以保新鲜 "
                            f"（累计 {self._drop_count} 次，最近: {event.type}）"
                        )
                except asyncio.QueueEmpty:
                    pass

    async def put_async(self, event_type: str, data: Any) -> None:
        """
        异步发送事件到队列，支持跨线程安全调用

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if not self._running or self._loop is None:
            logger.warning(f"[{self._name}] 事件引擎未运行，丢弃事件: {event_type}")
            return

        event = Event(event_type, data)

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is self._loop:
            # 关键事件走关键队列（满时等待空位，不丢弃）
            if event.type in self.CRITICAL_EVENT_TYPES:
                await self._critical_queue.put(event)
            else:
                await self._queue.put(event)
        else:
            # 跨线程：通过 call_soon_threadsafe 投递
            self._loop.call_soon_threadsafe(self._safe_put, event)

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
