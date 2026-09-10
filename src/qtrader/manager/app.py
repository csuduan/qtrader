"""
Q-Trader 应用主入口
包含应用启动、FastAPI应用创建、TradingManager管理
"""

import asyncio
import importlib
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import orjson
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi_offline import FastAPIOffline
from starlette.exceptions import HTTPException as StarletteHTTPException

from qtrader.app_context import AppContext, get_app_context
from qtrader.manager.api.middleware.auth import AuthMiddleware
from qtrader.manager.api.responses import (
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from qtrader.manager.api.websocket_manager import websocket_manager
from qtrader.manager.manager import TradingManager
from qtrader.utils.async_database import AsyncDatabase, close_async_database, init_async_database
from qtrader.utils.async_event_engine import AsyncEventEngine, Event
from qtrader.utils.config_loader import (
    AccountConfig,
    DatabaseConfig,
    get_config_loader,
    get_database_path,
    get_log_dir,
)
from qtrader.utils.db_url import build_async_db_url
from qtrader.utils.executors import init_executors, shutdown_executors
from qtrader.utils.logger import get_logger, setup_logger

logger = get_logger(__name__)
ctx = get_app_context()

_app_config = get_config_loader().load_config()
ctx.set(AppContext.KEY_CONFIG, _app_config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # ==================== 启动事件 ====================
    logger.info("=" * 60)
    logger.info("Q-Trader系统启动")

    # 存储主事件循环到 AppContext
    try:
        loop = asyncio.get_running_loop()
        ctx.set(AppContext.KEY_EVENT_LOOP, loop)
        logger.info("主事件循环已存储到 AppContext")
    except RuntimeError as e:
        logger.warning(f"无法获取运行中的事件循环: {e}")

    # 加载所有账户配置
    logger.info(f"已加载 {len(_app_config.accounts)} 个账户配置")

    # 设置日志
    log_dir = Path(_app_config.paths.logs) / "manager"
    log_dir.mkdir(parents=True, exist_ok=True)
    setup_logger(
        app_name="manager",
        log_dir=str(log_dir),
        log_level="INFO",
    )

    # 写入 Manager PID 文件（供 run_health.py 健康检查使用）
    try:
        pid_dir = Path(_app_config.socket.socket_dir)
        pid_dir.mkdir(parents=True, exist_ok=True)
        manager_pid_file = pid_dir / "qtrader_manager.pid"
        manager_pid_file.write_text(str(os.getpid()))
        logger.info(f"Manager PID 文件已写入: {manager_pid_file}")
    except Exception as e:
        logger.warning(f"写入 Manager PID 文件失败: {e}")

    # 初始化统一共享数据库（PostgreSQL，异步）
    db_config = _app_config.data_base
    assert db_config is not None, "数据库配置缺失"
    db_url = build_async_db_url(db_config)
    _manager_db: AsyncDatabase = await init_async_database(
        db_url,
        account_id="manager",
        echo=False,
        pool_size=db_config.pg.pool_size,
        max_overflow=db_config.pg.max_overflow,
    )
    logger.info(f"共享数据库已初始化: {_manager_db}")

    # 初始化执行器（注册主事件循环、创建独立线程池）
    init_executors()

    # 初始化默认用户
    try:
        from qtrader.manager.api.routes.auth import init_default_users

        await init_default_users()
    except Exception as e:
        logger.error(f"初始化默认用户失败: {e}")

    # 启用告警日志处理器
    try:
        from qtrader.utils.logger import enable_alarm_handler

        enable_alarm_handler()
    except Exception as e:
        logger.error(f"启用告警日志处理器失败: {e}")

    active_accounts = [acc for acc in _app_config.accounts if acc.enabled]
    logger.info(f"启用账号: {[a.account_id for a in active_accounts]}")
    logger.info("=" * 60)

    # 提取所有账户
    all_accounts = _app_config.accounts
    active_accounts = [acc for acc in all_accounts if acc.enabled]
    disabled_accounts = [acc for acc in all_accounts if not acc.enabled]
    # 提取所有账户
    all_accounts = _app_config.accounts
    active_accounts = [acc for acc in all_accounts if acc.enabled]
    disabled_accounts = [acc for acc in all_accounts if not acc.enabled]
    _event_engine = AsyncEventEngine()
    _event_engine.start()
    # 创建交易管理器（传入账户配置和全局配置）
    _trading_manager = TradingManager(all_accounts, _app_config)

    # 使用 AppContext 设置全局状态
    ctx.set(AppContext.KEY_EVENT_ENGINE, _event_engine)
    ctx.set(AppContext.KEY_TRADING_MANAGER, _trading_manager)

    # 启动管理器（异步）
    await _trading_manager.start()

    # 启动 WebSocket 管理器
    websocket_manager.start()
    ctx.set(AppContext.KEY_WS_MANAGER, websocket_manager)

    # 存储到app.state
    app.state.config = _app_config
    app.state.context = ctx
    app.state.db = _manager_db

    logger.info("FastAPI应用启动完成")
    logger.info(f"API文档: http://{_app_config.api.host}:{_app_config.api.port}/docs")
    logger.info(f"WebSocket: ws://{_app_config.api.host}:{_app_config.api.port}/ws")

    yield

    # ==================== 关闭事件 ====================
    logger.info("FastAPI应用关闭中...")
    # 清理 Manager PID 文件
    try:
        manager_pid_file = Path(_app_config.socket.socket_dir) / "qtrader_manager.pid"
        if manager_pid_file.exists():
            manager_pid_file.unlink()
    except Exception as e:
        logger.warning(f"清理 Manager PID 文件失败: {e}")

    # 停止交易管理器
    if _trading_manager:
        await _trading_manager.stop()

    # 停止事件引擎
    if _event_engine:
        await _event_engine.stop()

    # 关闭数据库
    await close_async_database()

    # 关闭执行器
    shutdown_executors()

    # 清理 AppContext
    ctx.clear()

    logger.info("Q-Trader系统已关闭")


def create_app() -> FastAPI:
    """
    创建FastAPI应用实例

    Returns:
        FastAPI应用实例
    """
    app = FastAPIOffline(
        title="Q-Trader自动化交易系统",
        description="Q-Trader自动化交易系统API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 配置CORS（在lifespan中已设置config，这里使用默认配置）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册鉴权中间件（必须在CORS之后，路由之前）
    app.add_middleware(AuthMiddleware)

    @app.middleware("http")
    async def add_response_time(request: Request, call_next):
        """添加响应时间中间件"""
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Response-Time"] = str(process_time)
        logger.info(
            f"{request.method} {request.url.path} - "
            f"Status: {response.status_code} - "
            f"Time: {process_time:.3f}s"
        )
        return response

    # 注册全局异常处理器
    app.add_exception_handler(Exception, global_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]

    # 动态注册路由
    _register_routes(app)

    @app.get("/")
    async def root():
        """根路径"""
        return {
            "name": "Q-Trader系统",
            "version": "0.1.0",
            "status": "running",
        }

    @app.get("/health")
    async def health_check():
        """健康检查"""
        return {"status": "ok"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket端点（握手时校验 token，未认证拒绝连接）"""
        from qtrader.manager.api.routes.auth import verify_token

        token = websocket.query_params.get("token", "")
        if not token or verify_token(token) is None:
            logger.warning("WebSocket 鉴权失败，拒绝连接")
            await websocket.close(code=4401)
            return

        await websocket_manager.connect(websocket)

        try:
            # 发送连接成功消息
            await websocket.send_text(
                orjson.dumps(
                    {
                        "type": "connected",
                        "message": "WebSocket连接成功",
                        "timestamp": datetime.now().isoformat(),
                    }
                ).decode("utf-8")
            )

            # 保持连接并接收客户端消息
            while True:
                data = await websocket.receive_text()
                try:
                    msg_data = orjson.loads(data)
                    logger.debug(f"收到WebSocket消息: {data}")

                    msg_type = msg_data.get("type")
                    if msg_type == "subscribe_quotes":
                        websocket_manager.set_quote_subscription(websocket, True)
                    elif msg_type == "unsubscribe_quotes":
                        websocket_manager.set_quote_subscription(websocket, False)

                except orjson.JSONDecodeError:
                    logger.warning(f"WebSocket消息解析失败: {data}")

        except WebSocketDisconnect:
            await websocket_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket连接出错: {e}")
            await websocket_manager.disconnect(websocket)

    return app


def _register_routes(app: FastAPI) -> None:
    """
    动态注册路由

    自动发现 src/manager/api/routes 目录下所有路由模块并注册

    Args:
        app: FastAPI应用实例
    """
    routes_dir = Path(__file__).parent / "api" / "routes"

    if not routes_dir.exists():
        logger.warning(f"路由目录不存在: {routes_dir}")
        return

    # 排除的文件
    excluded_files = {"__init__.py", "__pycache__"}

    registered_count = 0
    for file_path in routes_dir.glob("*.py"):
        if file_path.name in excluded_files:
            continue

        module_name = f"qtrader.manager.api.routes.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)

            # 查找 router 对象
            if hasattr(module, "router"):
                router = getattr(module, "router")
                app.include_router(router)
                registered_count += 1
                logger.info(f"已注册路由: {module_name}")
            else:
                logger.warning(f"路由模块 {module_name} 未找到 router 对象")

        except Exception as e:
            logger.exception(f"加载路由模块 {module_name} 失败: {e}")

    logger.info(f"动态注册完成，共注册 {registered_count} 个路由模块")


def main():
    """主函数"""
    # 创建并运行应用
    app = create_app()

    try:
        uvicorn.run(
            app,
            host=_app_config.api.host,
            port=_app_config.api.port,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("收到键盘中断信号")
    finally:
        logger.info("程序已退出")


# 导出
__all__ = ["create_app", "main", "websocket_manager"]


if __name__ == "__main__":
    main()
