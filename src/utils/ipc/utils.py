"""
IPC工具模块

提供通用的工具类和辅助函数：
- BackoffStrategy: 退避策略，用于重连间隔计算
- HealthChecker: 健康检查器
- RequestHandlerRegistry: 请求处理器注册表
"""

import asyncio
import hashlib
import time
import uuid
from functools import wraps
from typing import Any, Callable, Dict, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class BackoffStrategy:
    """
    退避策略

    用于计算重连间隔时间，采用指数退避算法：
    - 初始延迟：initial_delay
    - 每次重连后延迟增加 multiplier 倍
    - 最大延迟不超过 max_delay

    Example:
        backoff = BackoffStrategy(initial_delay=0.5, max_delay=15.0, multiplier=1.5)
        delay1 = backoff.get_delay()  # 0.5
        delay2 = backoff.get_delay()  # 0.75
        delay3 = backoff.get_delay()  # 1.125
        ...
    """

    def __init__(
        self, initial_delay: float = 0.5, max_delay: float = 15.0, multiplier: float = 1.5
    ):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self._current_delay: float = initial_delay

    def get_delay(self) -> float:
        """获取当前延迟时间并计算下一次延迟"""
        delay = self._current_delay
        self._current_delay = min(self._current_delay * self.multiplier, self.max_delay)
        return delay

    def reset(self) -> None:
        """重置延迟时间到初始值"""
        self._current_delay = self.initial_delay


class HealthChecker:
    """
    健康检查器

    定期检查连接健康状态，通过发送心跳包检测连接是否可用。

    Attributes:
        interval: 检查间隔（秒）
        timeout: 心跳超时时间（秒）
    """

    def __init__(self, interval: float = 5.0, timeout: float = 3.0):
        self.interval = interval
        self.timeout = timeout
        self._last_check: float = 0.0
        self._healthy = True

    async def check(self, heartbeat_func: Callable[[], Any]) -> bool:
        """
        执行健康检查

        Args:
            heartbeat_func: 心跳函数，应该返回一个可await的对象

        Returns:
            健康状态是否良好
        """
        current_time = time.time()
        if current_time - self._last_check < self.interval:
            return self._healthy

        try:
            # 发送心跳包，设置超时
            await asyncio.wait_for(heartbeat_func(), timeout=self.timeout)
            self._healthy = True
        except (asyncio.TimeoutError, ConnectionError) as e:
            logger.warning(f"健康检查失败: {e}")
            self._healthy = False
        except Exception as e:
            logger.warning(f"健康检查时出错: {e}")
            self._healthy = False

        self._last_check = time.time()
        return self._healthy

    def is_healthy(self) -> bool:
        """获取当前健康状态（可能不是最新的）"""
        return self._healthy


class RequestHandlerRegistry:
    """
    请求处理器注册表

    用于注册和管理请求处理器，支持装饰器方式注册。

    Example:
        registry = RequestHandlerRegistry()

        @registry.register("echo")
        async def handle_echo(data: dict) -> dict:
            return {"echo": data}

        handler = registry.get_handler("echo")
    """

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}

    def register(self, request_type: str) -> Callable:
        """
        注册请求处理器的装饰器

        Args:
            request_type: 请求类型标识

        Returns:
            装饰器函数
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)

            self._handlers[request_type] = wrapper
            return wrapper

        return decorator

    def get_handler(self, request_type: str) -> Optional[Callable]:
        """获取处理器"""
        return self._handlers.get(request_type)

    def has_handler(self, request_type: str) -> bool:
        """检查是否有处理器"""
        return request_type in self._handlers

    def remove_handler(self, request_type: str) -> bool:
        """移除处理器"""
        if request_type in self._handlers:
            del self._handlers[request_type]
            return True
        return False

    def list_handlers(self) -> list:
        """列出所有已注册的处理器类型"""
        return list(self._handlers.keys())


def generate_request_id() -> str:
    """生成请求ID"""
    try:
        task = asyncio.current_task()
        task_id = id(task) if task else 0
    except RuntimeError:
        task_id = 0
    return hashlib.md5(f"{time.time()}{task_id}{uuid.uuid4().hex}".encode()).hexdigest()[:16]
