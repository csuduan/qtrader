"""
事件类型常量定义（向后兼容）

已废弃：请使用 src.utils.event_engine 模块中的独立 EventEngine 类。
本文件仅保留事件类型常量用于向后兼容。
"""

from src.utils.event_engine import Event, EventEngine, EventTypes  # noqa: F401

# 向后兼容：保持导出
__all__ = ["Event", "EventTypes", "EventEngine"]
