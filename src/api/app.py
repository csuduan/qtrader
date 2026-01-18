"""
FastAPI应用主文件
包含API路由、WebSocket连接管理和CORS配置
"""
import asyncio
import json
import time
from datetime import datetime

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.routes.account import router as account_router
from src.api.routes.alarm import router as alarm_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.order import router as order_router
from src.api.routes.position import router as position_router
from src.api.routes.quote import router as quote_router
from src.api.routes.rotation import router as rotation_router
from src.api.routes.system import router as system_router
from src.api.routes.trade import router as trade_router
from src.api.schemas import AccountRes, OrderRes, PositionRes, TradeRes
from src.api.responses import (
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler
)
from src.api.websocket_manager import websocket_manager
from src.utils.event import event_engine, EventTypes, Event
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_app(config=None) -> FastAPI:
    """
    创建FastAPI应用实例

    Args:
        config: 应用配置（可选）

    Returns:
        FastAPI应用实例
    """
    app = FastAPI(
        title="Q-Trader自动化交易系统",
        description="基于TqSdk的自动化交易系统API",
        version="0.1.0",
    )

    # 配置CORS
    if config and config.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        # 默认CORS配置
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

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
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # 注册路由
    app.include_router(account_router)
    app.include_router(position_router)
    app.include_router(trade_router)
    app.include_router(order_router)
    app.include_router(quote_router)
    app.include_router(jobs_router)
    app.include_router(rotation_router)
    app.include_router(system_router)
    app.include_router(alarm_router)

    @app.on_event("startup")
    async def startup_event():
        """应用启动事件"""
        logger.info("FastAPI应用启动")

        # 获取当前运行的事件循环（主线程Loop）
        loop = asyncio.get_running_loop()

        def handle_account_update(event: Event):
            asyncio.run_coroutine_threadsafe(websocket_manager.broadcast_account(event.data), loop)

        def handle_position_update(event: Event):
            asyncio.run_coroutine_threadsafe(websocket_manager.broadcast_position(event.data), loop)

        def handle_order_update(event: Event):
            asyncio.run_coroutine_threadsafe(websocket_manager.broadcast_order(event.data), loop)

        def handle_trade_update(event: Event):
            asyncio.run_coroutine_threadsafe(websocket_manager.broadcast_trade(event.data), loop)

        def handle_tick_update(event: Event):
            asyncio.run_coroutine_threadsafe(websocket_manager.broadcast_quote(event.data), loop)

        event_engine.register(EventTypes.ACCOUNT_UPDATE, handle_account_update)
        event_engine.register(EventTypes.POSITION_UPDATE, handle_position_update)
        event_engine.register(EventTypes.ORDER_UPDATE, handle_order_update)
        event_engine.register(EventTypes.TRADE_UPDATE, handle_trade_update)
        event_engine.register(EventTypes.TICK_UPDATE, handle_tick_update)

        logger.info("已注册事件引擎订阅")

    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭事件"""
        logger.info("FastAPI应用关闭")

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
        return {"status": "healthy"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket端点"""
        await websocket_manager.connect(websocket)

        try:
            # 发送连接成功消息
            await websocket.send_text(json.dumps({
                "type": "connected",
                "message": "WebSocket连接成功",
                "timestamp": datetime.now().isoformat(),
            }, ensure_ascii=False))

            # 保持连接并接收客户端消息
            while True:
                data = await websocket.receive_text()
                try:
                    msg_data = json.loads(data)
                    logger.debug(f"收到WebSocket消息: {data}")
                except json.JSONDecodeError:
                    logger.warning(f"WebSocket消息解析失败: {data}")

        except WebSocketDisconnect:
            websocket_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket连接出错: {e}")
            websocket_manager.disconnect(websocket)

    return app


# 导出WebSocket管理器实例
__all__ = ["create_app", "websocket_manager"]
