"""
AsyncEventEngine 单元测试

测试异步事件引擎的核心功能，包括：
- 初始化
- 启动/停止
- 注册/注销处理器
- 发送事件
- 事件处理
- 清空处理器
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from qtrader.utils.async_event_engine import AsyncEventEngine, Event, EventTypes, HandlerType

# ==================== Fixtures ====================


@pytest.fixture
def event_engine() -> AsyncEventEngine:
    """创建事件引擎实例"""
    return AsyncEventEngine(name="TestEventEngine")


@pytest.fixture
def sync_handler():
    """创建同步处理器"""
    handler = MagicMock()
    handler.return_value = None
    return handler


@pytest.fixture
def async_handler():
    """创建异步处理器"""
    handler = AsyncMock()
    return handler


# ==================== TestAsyncEventEngineInitialization ====================


class TestAsyncEventEngineInitialization:
    """AsyncEventEngine 初始化测试"""

    def test_initialization_basic_attributes(self, event_engine: AsyncEventEngine):
        """测试基本属性初始化"""
        assert event_engine._name == "TestEventEngine"
        assert event_engine._running is False
        assert event_engine._process_tasks == []
        assert event_engine._pending_puts == set()

    def test_initialization_queue(self, event_engine: AsyncEventEngine):
        """测试队列初始化"""
        assert isinstance(event_engine._queue, asyncio.Queue)
        assert isinstance(event_engine._critical_queue, asyncio.Queue)
        assert event_engine._critical_queue.maxsize > event_engine._queue.maxsize

    def test_initialization_handlers(self, event_engine: AsyncEventEngine):
        """测试处理器字典初始化"""
        from collections import defaultdict

        assert isinstance(event_engine._handlers, defaultdict)
        assert len(event_engine._handlers) == 0
        assert isinstance(event_engine._general_handlers, list)
        assert len(event_engine._general_handlers) == 0


# ==================== TestAsyncEventEngineStartStop ====================


class TestAsyncEventEngineStartStop:
    """AsyncEventEngine 启动停止测试"""

    @pytest.mark.asyncio
    async def test_start_creates_background_task(self, event_engine: AsyncEventEngine):
        """测试 start() 创建后台任务"""
        event_engine.start()

        assert event_engine._running is True
        # 在异步上下文中运行，任务应该被创建
        # 注意：task 可能为 None 如果事件循环未正确设置
        # 主要验证 running 状态
        await event_engine.stop()

    def test_start_already_running(self, event_engine: AsyncEventEngine):
        """测试重复启动处理"""
        event_engine._running = True

        event_engine.start()

        # 应该不创建新任务
        assert event_engine._process_tasks == []

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, event_engine: AsyncEventEngine):
        """测试 stop() 设置 _running 为 False"""
        event_engine.start()

        await event_engine.stop()

        assert event_engine._running is False

    @pytest.mark.asyncio
    async def test_start_creates_two_consumer_tasks(self, event_engine: AsyncEventEngine):
        """测试 start() 创建两个消费任务（普通 + 关键队列各一个）"""
        event_engine.start()

        assert len(event_engine._process_tasks) == 2
        assert all(not t.done() for t in event_engine._process_tasks)

        await event_engine.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_process_tasks(self, event_engine: AsyncEventEngine):
        """测试 stop() 取消全部消费任务"""
        event_engine.start()

        await event_engine.stop()

        assert event_engine._process_tasks == []

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, event_engine: AsyncEventEngine):
        """测试未运行时停止"""
        # 应该不报错
        await event_engine.stop()

        assert event_engine._running is False

    def test_running_property(self, event_engine: AsyncEventEngine):
        """测试 running 属性正确反映状态"""
        assert event_engine.running is False

        event_engine._running = True
        assert event_engine.running is True


# ==================== TestAsyncEventEngineRegister ====================


class TestAsyncEventEngineRegister:
    """AsyncEventEngine 注册测试"""

    def test_register_adds_handler(self, event_engine: AsyncEventEngine, sync_handler):
        """测试 register() 注册特定类型处理器"""
        event_engine.register("TEST_EVENT", sync_handler)

        assert "TEST_EVENT" in event_engine._handlers
        assert sync_handler in event_engine._handlers["TEST_EVENT"]

    def test_register_multiple_handlers_same_type(self, event_engine: AsyncEventEngine):
        """测试注册多个同一类型的处理器"""
        handler1 = MagicMock()
        handler2 = MagicMock()

        event_engine.register("TEST_EVENT", handler1)
        event_engine.register("TEST_EVENT", handler2)

        assert len(event_engine._handlers["TEST_EVENT"]) == 2
        assert handler1 in event_engine._handlers["TEST_EVENT"]
        assert handler2 in event_engine._handlers["TEST_EVENT"]

    def test_register_general_adds_to_general_list(
        self, event_engine: AsyncEventEngine, sync_handler
    ):
        """测试 register_general() 注册通用处理器"""
        event_engine.register_general(sync_handler)

        assert sync_handler in event_engine._general_handlers

    def test_register_general_multiple_handlers(self, event_engine: AsyncEventEngine):
        """测试注册多个通用处理器"""
        handler1 = MagicMock()
        handler2 = MagicMock()

        event_engine.register_general(handler1)
        event_engine.register_general(handler2)

        assert len(event_engine._general_handlers) == 2

    def test_unregister_removes_handler(self, event_engine: AsyncEventEngine):
        """测试 unregister() 注销处理器"""
        handler = MagicMock()
        event_engine.register("TEST_EVENT", handler)

        event_engine.unregister("TEST_EVENT", handler)

        assert handler not in event_engine._handlers["TEST_EVENT"]

    def test_unregister_removes_empty_type(self, event_engine: AsyncEventEngine):
        """测试注销后删除空类型"""
        handler = MagicMock()
        event_engine.register("TEST_EVENT", handler)

        event_engine.unregister("TEST_EVENT", handler)

        assert "TEST_EVENT" not in event_engine._handlers

    def test_unregister_general_removes_handler(self, event_engine: AsyncEventEngine):
        """测试 unregister_general() 注销通用处理器"""
        handler = MagicMock()
        event_engine.register_general(handler)

        event_engine.unregister_general(handler)

        assert handler not in event_engine._general_handlers


# ==================== TestAsyncEventEnginePut ====================


class TestAsyncEventEnginePut:
    """AsyncEventEngine 发送事件测试"""

    @pytest.mark.asyncio
    async def test_put_sends_to_queue(self, event_engine: AsyncEventEngine):
        """测试 put() 投递事件并被分发"""
        received = []
        event_engine.register_general(lambda e: received.append(e))
        event_engine.start()

        event_engine.put("TEST_EVENT", {"data": "test"})

        # 等待事件引擎处理（put后事件应被分发到处理器）
        for _ in range(20):
            await asyncio.sleep(0.01)
            if received:
                break
        assert received == [{"data": "test"}]

    def test_put_when_not_running_drops_event(self, event_engine: AsyncEventEngine):
        """测试未运行时丢弃事件"""
        # 未运行时 put 不应该抛出异常
        event_engine.put("TEST_EVENT", {"data": "test"})

    @pytest.mark.asyncio
    async def test_put_async_sends_to_queue(self, event_engine: AsyncEventEngine):
        """测试 put_async() 异步发送到队列"""
        event_engine.start()

        await event_engine.put_async("TEST_EVENT", {"data": "test"})

        # 验证事件在队列中
        assert not event_engine._queue.empty()

    @pytest.mark.asyncio
    async def test_put_async_critical_event_goes_to_critical_queue(
        self, event_engine: AsyncEventEngine
    ):
        """测试 put_async() 关键事件进入关键队列"""
        event_engine.start()

        await event_engine.put_async(EventTypes.ORDER_UPDATE, {"data": "test"})

        assert event_engine._critical_queue.qsize() == 1
        assert event_engine._queue.empty()

        await event_engine.stop()

    def test_safe_put_droppable_event_evicts_oldest(self):
        """普通队列（行情）满时丢弃最旧以容纳新事件"""
        engine = AsyncEventEngine(queue_size=2)
        # 手动填满普通队列（不启动，直接操作 _safe_put）
        engine._queue.put_nowait(Event(EventTypes.TICK_UPDATE, {"n": 1}))
        engine._queue.put_nowait(Event(EventTypes.TICK_UPDATE, {"n": 2}))

        engine._safe_put(Event(EventTypes.TICK_UPDATE, {"n": 3}))

        # 最旧的 n=1 被丢弃，队列保留 2,3
        items = [engine._queue.get_nowait().data["n"] for _ in range(2)]
        assert items == [2, 3]
        assert engine._drop_count == 1

    def test_safe_put_routes_by_event_type(self):
        """按事件类型分流：关键事件入关键队列，普通事件入普通队列"""
        engine = AsyncEventEngine()

        engine._safe_put(Event(EventTypes.ORDER_UPDATE, {"n": 1}))
        engine._safe_put(Event(EventTypes.TRADE_UPDATE, {"n": 2}))
        engine._safe_put(Event(EventTypes.TICK_UPDATE, {"n": 3}))
        engine._safe_put(Event("UNKNOWN_TYPE", {"n": 4}))  # 未注册类型归普通

        assert engine._critical_queue.qsize() == 2
        assert engine._queue.qsize() == 2
        assert engine._critical_queue.get_nowait().type == EventTypes.ORDER_UPDATE
        assert engine._critical_queue.get_nowait().type == EventTypes.TRADE_UPDATE
        assert engine._queue.get_nowait().type == EventTypes.TICK_UPDATE
        assert engine._queue.get_nowait().type == "UNKNOWN_TYPE"

    @pytest.mark.asyncio
    async def test_safe_put_critical_event_not_dropped_on_full(self):
        """关键队列满时事件不丢弃：调度等待任务，取出一个后补位入队"""
        engine = AsyncEventEngine(critical_queue_size=1)
        engine._critical_queue.put_nowait(Event(EventTypes.ORDER_UPDATE, {"n": 1}))

        engine._safe_put(Event(EventTypes.ORDER_UPDATE, {"n": 2}))

        # 队列仍满（等待任务尚未执行），但已调度等待任务
        assert engine._critical_queue.qsize() == 1
        assert len(engine._pending_puts) == 1
        assert engine._drop_count == 1

        # 取走一个事件腾出空位，等待任务完成后 n=2 补位入队
        assert engine._critical_queue.get_nowait().data["n"] == 1
        await asyncio.sleep(0.05)
        assert engine._pending_puts == set()
        assert engine._critical_queue.qsize() == 1
        assert engine._critical_queue.get_nowait().data["n"] == 2

    @pytest.mark.asyncio
    async def test_critical_events_processed_before_backlogged_normal_events(self):
        """优先级：普通队列积压时，后到的关键事件仍先被处理"""
        engine = AsyncEventEngine(queue_size=10)
        processed: list[str] = []

        async def slow_handler(data: Any) -> None:
            await asyncio.sleep(0.01)
            processed.append(data["tag"])

        engine.register_general(slow_handler)
        # 预填普通队列积压（引擎未启动，直接入队）
        for i in range(5):
            engine._queue.put_nowait(Event(EventTypes.TICK_UPDATE, {"tag": f"tick{i}"}))

        engine.start()
        await asyncio.sleep(0.001)  # 让消费者取走第一个 tick 并开始慢处理
        engine.put(EventTypes.ORDER_UPDATE, {"tag": "order0"})

        await asyncio.sleep(0.2)

        # 关键事件 order0 不必等 5 个 tick 全部消化完，应在前几位
        assert processed.index("order0") <= 2
        assert processed[-1] is not None

        await engine.stop()

    @pytest.mark.asyncio
    async def test_sync_normal_events_do_not_starve_critical_consumer(self):
        """同步处理器饿死防护：普通队列连续消化同步事件时让出控制权，关键事件不被拖尾"""
        engine = AsyncEventEngine()
        processed: list[str] = []

        # 同步处理器：全程不 yield，若无让出逻辑普通消费者会独占事件循环
        engine.register_general(lambda data: processed.append(data["tag"]))
        # 启动前预填两个队列：普通队列积压 + 关键事件
        for i in range(20):
            engine._queue.put_nowait(Event(EventTypes.TICK_UPDATE, {"tag": f"tick{i}"}))
        engine._critical_queue.put_nowait(Event(EventTypes.ORDER_UPDATE, {"tag": "order0"}))

        engine.start()
        await asyncio.sleep(0.2)

        # order0 不应排在 20 个 tick 积压之后
        assert processed.index("order0") <= 2

        await engine.stop()

    @pytest.mark.asyncio
    async def test_events_processed_serially_across_queues(self):
        """处理串行性：两个队列的事件经处理锁串行执行，不交错"""
        engine = AsyncEventEngine()
        enter: set[str] = set()
        overlap_detected = []

        async def checking_handler(data: Any) -> None:
            tag = data["tag"]
            if tag in enter:
                overlap_detected.append(tag)
            enter.add(tag)
            await asyncio.sleep(0.005)
            enter.discard(tag)

        engine.register_general(checking_handler)
        engine.start()

        for i in range(5):
            engine.put(EventTypes.TICK_UPDATE, {"tag": f"tick{i}"})
            engine.put(EventTypes.ORDER_UPDATE, {"tag": f"order{i}"})

        await asyncio.sleep(0.3)

        assert overlap_detected == []

        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_drains_both_queues_critical_first(self):
        """stop() 排空两个队列，关键队列优先处理"""
        engine = AsyncEventEngine(queue_size=10)
        processed: list[str] = []

        engine.register_general(lambda data: processed.append(data["tag"]))
        # 预填两个队列
        engine._queue.put_nowait(Event(EventTypes.TICK_UPDATE, {"tag": "tick0"}))
        engine._critical_queue.put_nowait(Event(EventTypes.ORDER_UPDATE, {"tag": "order0"}))

        engine.start()
        await engine.stop(drain_timeout=2.0)

        assert "order0" in processed
        assert "tick0" in processed
        assert processed.index("order0") < processed.index("tick0")
        assert engine._queue.empty()
        assert engine._critical_queue.empty()


# ==================== TestAsyncEventEngineProcess ====================


class TestAsyncEventEngineProcess:
    """AsyncEventEngine 事件处理测试"""

    @pytest.mark.asyncio
    async def test_sync_handler_called(self, event_engine: AsyncEventEngine):
        """测试同步处理器正确调用"""
        handler = MagicMock()
        event_engine.register("TEST_EVENT", handler)
        event_engine.start()

        event_engine.put("TEST_EVENT", {"data": "test"})

        # 等待事件处理
        await asyncio.sleep(0.1)

        handler.assert_called_once_with({"data": "test"})

    @pytest.mark.asyncio
    async def test_async_handler_called(self, event_engine: AsyncEventEngine):
        """测试异步处理器正确调用"""
        handler = AsyncMock()
        event_engine.register("TEST_EVENT", handler)
        event_engine.start()

        event_engine.put("TEST_EVENT", {"data": "test"})

        # 等待事件处理
        await asyncio.sleep(0.1)

        handler.assert_called_once_with({"data": "test"})

    @pytest.mark.asyncio
    async def test_handler_exception_doesnt_interrupt_others(self, event_engine: AsyncEventEngine):
        """测试处理器异常不中断其他处理器"""
        handler1 = MagicMock(side_effect=Exception("测试异常"))
        handler2 = MagicMock()

        event_engine.register("TEST_EVENT", handler1)
        event_engine.register("TEST_EVENT", handler2)
        event_engine.start()

        event_engine.put("TEST_EVENT", {"data": "test"})

        # 等待事件处理
        await asyncio.sleep(0.1)

        # handler2 应该仍然被调用
        handler2.assert_called_once()

    @pytest.mark.asyncio
    async def test_general_handler_receives_all_events(self, event_engine: AsyncEventEngine):
        """测试通用处理器接收所有事件"""
        general_handler = MagicMock()
        event_engine.register_general(general_handler)
        event_engine.start()

        event_engine.put("EVENT1", {"data": "test1"})
        await asyncio.sleep(0.1)
        event_engine.put("EVENT2", {"data": "test2"})
        await asyncio.sleep(0.1)

        assert general_handler.call_count == 2

    @pytest.mark.asyncio
    async def test_multiple_sync_handlers_concurrent(self, event_engine: AsyncEventEngine):
        """测试多个同步处理器并发执行"""
        import time

        handler1 = MagicMock()
        handler2 = MagicMock()

        event_engine.register("TEST_EVENT", handler1)
        event_engine.register("TEST_EVENT", handler2)
        event_engine.start()

        event_engine.put("TEST_EVENT", {"data": "test"})

        # 等待事件处理
        await asyncio.sleep(0.1)

        # 两个处理器都应该被调用
        handler1.assert_called_once()
        handler2.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_data_passed_correctly(self, event_engine: AsyncEventEngine):
        """测试事件数据正确传递"""
        handler = MagicMock()
        test_data = {"key": "value", "number": 123}

        event_engine.register("TEST_EVENT", handler)
        event_engine.start()

        event_engine.put("TEST_EVENT", test_data)

        # 等待事件处理
        await asyncio.sleep(0.1)

        handler.assert_called_once_with(test_data)


# ==================== TestAsyncEventEngineClear ====================


class TestAsyncEventEngineClear:
    """AsyncEventEngine 清空测试"""

    def test_clear_removes_all_handlers(self, event_engine: AsyncEventEngine):
        """测试 clear() 清空所有处理器"""
        handler1 = MagicMock()
        handler2 = MagicMock()

        event_engine.register("EVENT1", handler1)
        event_engine.register("EVENT2", handler2)
        event_engine.register_general(handler1)

        event_engine.clear()

        assert len(event_engine._handlers) == 0
        assert len(event_engine._general_handlers) == 0


# ==================== TestAsyncEventEngineEdgeCases ====================


class TestAsyncEventEngineEdgeCases:
    """AsyncEventEngine 边界情况测试"""

    @pytest.mark.asyncio
    async def test_event_object_structure(self, event_engine: AsyncEventEngine):
        """测试 Event 对象结构"""
        event = Event("TEST_TYPE", {"data": "test"})

        assert event.type == "TEST_TYPE"
        assert event.data == {"data": "test"}

    @pytest.mark.asyncio
    async def test_no_handler_for_event_type(self, event_engine: AsyncEventEngine):
        """测试没有处理器的事件类型"""
        # 只注册通用处理器
        general_handler = MagicMock()
        event_engine.register_general(general_handler)
        event_engine.start()

        event_engine.put("UNHANDLED_EVENT", {"data": "test"})

        # 等待事件处理
        await asyncio.sleep(0.1)

        # 通用处理器应该被调用
        general_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_event_data(self, event_engine: AsyncEventEngine):
        """测试空事件数据"""
        handler = MagicMock()
        event_engine.register("TEST_EVENT", handler)
        event_engine.start()

        event_engine.put("TEST_EVENT", None)

        # 等待事件处理
        await asyncio.sleep(0.1)

        handler.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_rapid_events(self, event_engine: AsyncEventEngine):
        """测试快速连续发送事件"""
        handler = MagicMock()
        event_engine.register("TEST_EVENT", handler)
        event_engine.start()

        for i in range(10):
            event_engine.put("TEST_EVENT", {"index": i})

        # 等待事件处理
        await asyncio.sleep(0.5)

        assert handler.call_count == 10
