import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.utils.event import Event, EventEngine, EventTypes


@pytest.mark.unit
class TestEvent:
    """事件对象测试"""
    
    def test_event_creation(self):
        """测试事件对象创建"""
        event = Event(type="test.event", data={"key": "value"})
        assert event.type == "test.event"
        assert event.data == {"key": "value"}
    
    def test_event_without_data(self):
        """测试无数据的事件对象"""
        event = Event(type="test.event")
        assert event.type == "test.event"
        assert event.data is None


@pytest.mark.unit
class TestEventEngine:
    """事件引擎测试"""
    
    def test_event_engine_creation(self):
        """测试事件引擎创建"""
        engine = EventEngine()
        assert not engine._active
        assert len(engine._handlers) == 0
        assert len(engine._general_handlers) == 0
    
    def test_start_stop_event_engine(self):
        """测试启动和停止事件引擎"""
        engine = EventEngine()
        
        engine.start()
        assert engine._active
        assert engine._thread.is_alive()
        
        engine.stop()
        assert not engine._active
    
    def test_register_handler(self):
        """测试注册事件处理器"""
        engine = EventEngine()
        engine.start()
        
        def handler(event: Event):
            pass
        
        engine.register("test.event", handler)
        assert "test.event" in engine._handlers
        assert handler in engine._handlers["test.event"]
        
        engine.stop()
    
    def test_register_duplicate_handler(self):
        """测试重复注册同一处理器"""
        engine = EventEngine()
        engine.start()
        
        def handler(event: Event):
            pass
        
        engine.register("test.event", handler)
        engine.register("test.event", handler)
        
        assert len(engine._handlers["test.event"]) == 1
        
        engine.stop()
    
    def test_unregister_handler(self):
        """测试注销事件处理器"""
        engine = EventEngine()
        engine.start()
        
        def handler(event: Event):
            pass
        
        engine.register("test.event", handler)
        assert "test.event" in engine._handlers
        
        engine.unregister("test.event", handler)
        assert "test.event" not in engine._handlers
        
        engine.stop()
    
    def test_register_general_handler(self):
        """测试注册通用处理器"""
        engine = EventEngine()
        engine.start()
        
        def handler(event: Event):
            pass
        
        engine.register_general(handler)
        assert handler in engine._general_handlers
        
        engine.stop()
    
    def test_unregister_general_handler(self):
        """测试注销通用处理器"""
        engine = EventEngine()
        engine.start()
        
        def handler(event: Event):
            pass
        
        engine.register_general(handler)
        engine.unregister_general(handler)
        
        assert handler not in engine._general_handlers
        
        engine.stop()
    
    def test_put_and_process_event(self):
        """测试发布和处理事件"""
        engine = EventEngine()
        engine.start()
        
        received_events = []
        
        def handler(event: Event):
            received_events.append(event)
        
        engine.register("test.event", handler)
        
        engine.put("test.event", {"data": "test"})
        
        import time
        time.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].type == "test.event"
        assert received_events[0].data == {"data": "test"}
        
        engine.stop()
    
    def test_general_handler_receives_all_events(self):
        """测试通用处理器接收所有事件"""
        engine = EventEngine()
        engine.start()
        
        received_events = []
        
        def general_handler(event: Event):
            received_events.append(event.type)
        
        engine.register_general(general_handler)
        
        engine.put("event1", {})
        engine.put("event2", {})
        engine.put("event3", {})
        
        import time
        time.sleep(0.1)
        
        assert len(received_events) == 3
        assert "event1" in received_events
        assert "event2" in received_events
        assert "event3" in received_events
        
        engine.stop()
    
    def test_specific_and_general_handlers(self):
        """测试特定处理器和通用处理器同时工作"""
        engine = EventEngine()
        engine.start()
        
        specific_events = []
        general_events = []
        
        def specific_handler(event: Event):
            specific_events.append(event.type)
        
        def general_handler(event: Event):
            general_events.append(event.type)
        
        engine.register("specific.event", specific_handler)
        engine.register_general(general_handler)
        
        engine.put("specific.event", {})
        engine.put("other.event", {})
        
        import time
        time.sleep(0.1)
        
        assert len(specific_events) == 1
        assert "specific.event" in specific_events
        
        assert len(general_events) == 2
        assert "specific.event" in general_events
        assert "other.event" in general_events
        
        engine.stop()
    
    @patch('src.utils.event_engine.logger')
    def test_handler_exception_handling(self, mock_logger):
        """测试处理器异常处理"""
        engine = EventEngine()
        engine.start()
        
        def failing_handler(event: Event):
            raise ValueError("Test error")
        
        engine.register("test.event", failing_handler)
        engine.put("test.event", {})
        
        import time
        time.sleep(0.1)
        
        mock_logger.exception.assert_called()
        
        engine.stop()
    
    def test_event_types_constants(self):
        """测试事件类型常量"""
        assert EventTypes.ACCOUNT_UPDATE == "e:account.update"
        assert EventTypes.POSITION_UPDATE == "e:position.update"
        assert EventTypes.ORDER_UPDATE == "e:order.update"
        assert EventTypes.TRADE_UPDATE == "e:trade.created"
        assert EventTypes.TICK_UPDATE == "e:tick.update"
        assert EventTypes.KLINE_UPDATE == "e:kline.update"
        assert EventTypes.SYSTEM_ERROR == "e:system.error"
        assert EventTypes.ALARM_UPDATE == "e:alarm.update"
        assert EventTypes.DATA_UPDATE == "e:data.update"
