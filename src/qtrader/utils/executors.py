"""
统一执行器模块
按任务类型分层调度，避免重任务占满默认线程池饿死轻任务与 asyncio 内部使用

分层：
- submit_task:      轻量同步任务（<3s，文件IO等），走默认线程池
- submit_long_task: 重 IO 任务（外部接口拉取等），走独立命名线程池，与默认池隔离
- submit_cpu_task:  CPU 密集任务，走进程池（预留，当前无调用方）
- submit_loop:      从任意线程把协程/回调投递到主事件循环（loguru sink、APScheduler 等同步上下文）
"""

import asyncio
import inspect
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Callable, Coroutine, TypeVar, cast

from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# 独立 IO 线程池（默认 8 线程，重 IO 任务专用，与默认池隔离）
_io_executor: ThreadPoolExecutor | None = None

# 进程池（CPU 密集预留，延迟初始化）
_cpu_executor: ProcessPoolExecutor | None = None

# 主事件循环引用（由启动流程注册）
_main_loop: asyncio.AbstractEventLoop | None = None


def init_executors(io_pool_size: int = 8) -> None:
    """
    初始化执行器（在主事件循环启动后调用一次）

    Args:
        io_pool_size: 独立 IO 线程池大小
    """
    global _io_executor, _main_loop
    if _io_executor is None:
        _io_executor = ThreadPoolExecutor(max_workers=io_pool_size, thread_name_prefix="qtrader-io")
    _main_loop = asyncio.get_running_loop()
    logger.info(f"执行器已初始化: io_pool={io_pool_size}")


def shutdown_executors() -> None:
    """关闭执行器（进程退出前调用）"""
    global _io_executor, _cpu_executor, _main_loop
    if _io_executor:
        _io_executor.shutdown(wait=False)
        _io_executor = None
    if _cpu_executor:
        _cpu_executor.shutdown(wait=False)
        _cpu_executor = None
    _main_loop = None


async def submit_task(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    轻量同步任务（<3s），走默认线程池

    Args:
        func: 同步函数
        *args, **kwargs: 函数参数

    Returns:
        函数返回值
    """
    return await asyncio.to_thread(func, *args, **kwargs)


async def submit_long_task(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    重 IO 任务，走独立命名线程池（与默认池隔离，防止阻塞轻任务）

    Args:
        func: 同步函数
        *args, **kwargs: 函数参数

    Returns:
        函数返回值
    """
    if _io_executor is None:
        raise RuntimeError("执行器未初始化，请先调用 init_executors()")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_io_executor, lambda: func(*args, **kwargs))


async def submit_cpu_task(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    CPU 密集任务，走进程池（绕开 GIL）

    【预留接口，当前无调用方】启用场景：大规模K线计算、回测等 CPU 密集任务。
    注意：func 及其参数必须可 pickle，避免传复杂对象/闭包。

    Args:
        func: 顶层函数（模块级，可 pickle）
        *args, **kwargs: 函数参数（可 pickle）

    Returns:
        函数返回值
    """
    global _cpu_executor
    if _cpu_executor is None:
        _cpu_executor = ProcessPoolExecutor()
        logger.info("进程池已初始化（CPU 密集任务）")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_cpu_executor, lambda: func(*args, **kwargs))


def submit_loop(coro_or_func: Coroutine | Callable[[], Any]) -> Future | None:
    """
    从任意线程把协程/同步回调投递到主事件循环

    适用于 loguru sink、APScheduler 等无法 await 的同步上下文。

    Args:
        coro_or_func: 协程对象，或无参同步回调

    Returns:
        Future（可 .result() 阻塞取结果），主循环未运行时返回 None 并记日志降级
    """
    if _main_loop is None or _main_loop.is_closed():
        logger.warning("主事件循环未初始化，无法投递任务")
        return None
    if inspect.iscoroutine(coro_or_func):
        return asyncio.run_coroutine_threadsafe(coro_or_func, _main_loop)
    func = cast(Callable[[], Any], coro_or_func)
    return asyncio.run_coroutine_threadsafe(asyncio.to_thread(func), _main_loop)
