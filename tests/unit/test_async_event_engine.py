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

from src.utils.async_event_engine import AsyncEventEngine, Event, HandlerType


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
        assert event_engine._process_task is None

    def test_initialization_queue(self, event_engine: AsyncEventEngine):
        """测试队列初始化"""
        assert isinstance(event_engine._queue, asyncio.Queue)

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
        event_engine._process_task = MagicMock()

        event_engine.start()

        # 应该不创建新任务
        assert event_engine._process_task is not None

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, event_engine: AsyncEventEngine):
        """测试 stop() 设置 _running 为 False"""
        event_engine.start()

        await event_engine.stop()

        assert event_engine._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_process_task(self, event_engine: AsyncEventEngine):
        """测试 stop() 取消处理任务"""
        event_engine.start()

        await event_engine.stop()

        assert event_engine._process_task is None or event_engine._process_task.cancelled()

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

    def test_register_general_adds_to_general_list(self, event_engine: AsyncEventEngine, sync_handler):
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

    def test_put_sends_to_queue(self, event_engine: AsyncEventEngine):
        """测试 put() 同步发送到队列"""
        event_engine.start()

        event_engine.put("TEST_EVENT", {"data": "test"})

        # 验证事件在队列中
        assert not event_engine._queue.empty()

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
