"""
主程序入口
启动交易引擎、策略管理器和API服务
"""
import asyncio
import signal
import sys
from threading import Thread
from time import sleep

import uvicorn

from src.api.app import create_app, websocket_manager
from src.config_loader import AppConfig, ensure_directories, load_config
from src.context import set_config, set_task_scheduler, set_trading_engine, set_switch_pos_manager,set_strategy_manager
from src.database import init_database
from src.persistence import init_persistence
from src.scheduler import TaskScheduler
from src.strategy.strategy_manager import StrategyManager
from src.trading_engine import TradingEngine
from src.switch_mgr import SwitchPosManager
from src.utils.logger import get_logger, setup_logger

logger = get_logger(__name__)

# 全局变量
config: AppConfig|None = None
trading_engine: TradingEngine|None = None
strategy_manager: StrategyManager|None = None
task_scheduler: TaskScheduler|None = None
running = False



def signal_handler(signum, frame):
    """信号处理器"""
    global running
    logger.info(f"收到信号 {signum}，准备退出...")
    running = False

    # 停止所有策略
    if strategy_manager:
        strategy_manager.stop_all()

    # 断开连接
    if trading_engine:
        trading_engine.disconnect()

    # 关闭任务调度器
    if task_scheduler:
        task_scheduler.shutdown()

    sys.exit(0)


def main():
    """主函数"""
    global config, trading_engine, strategy_manager, task_scheduler, running

    # 加载配置
    config = load_config()
    set_config(config)

    # 设置日志
    setup_logger(
        log_dir=config.paths.logs,
        log_level="INFO",
    )

    # 启用告警日志处理器
    try:
        from src.utils.logger import enable_alarm_handler
        enable_alarm_handler()
    except Exception as e:
        logger.error(f"启用告警日志处理器失败: {e}")

    logger.info("=" * 60)
    logger.info("Q-Trader系统启动")
    logger.info("=" * 60)

    # 初始化数据库
    logger.info("初始化数据库...")
    init_database(config.paths.database)

    # 启动数据持久化服务
    logger.info("启动数据持久化服务...")
    init_persistence()

    # 创建交易引擎
    logger.info("创建交易引擎...")
    trading_engine = TradingEngine(config)
    set_trading_engine(trading_engine)
    trading_engine.connect()

    # 初始化策略管理器（在连接后初始化）
    logger.info("初始化策略管理器...")
    strategy_manager = StrategyManager()
    strategy_manager.init(config.paths.strategies, trading_engine)
    set_strategy_manager(strategy_manager)


    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 创建换仓管理器
    logger.info("创建换仓管理器...")
    switch_pos_manager = SwitchPosManager(config, trading_engine)
    set_switch_pos_manager(switch_pos_manager)

    # 订阅今日换仓记录中的合约
    logger.info("订阅今日换仓记录中的合约...")
    switch_pos_manager.subscribe_today_symbols()

    # 启动任务调度器
    logger.info("创建任务调度器...")
    task_scheduler = TaskScheduler(config, trading_engine)
    set_task_scheduler(task_scheduler)
    task_scheduler.start()

    # 启动FastAPI应用
    logger.info("创建FastAPI应用...")
    app = create_app(config)
    logger.info(f"启动API服务，监听 {config.api.host}:{config.api.port}")
    logger.info(f"API文档: http://{config.api.host}:{config.api.port}/docs")
    logger.info(f"WebSocket: ws://{config.api.host}:{config.api.port}/ws")

    try:
        uvicorn.run(
            app,
            host=config.api.host,
            port=config.api.port,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("收到键盘中断信号")
    finally:
        running = False
        # 停止所有策略
        if strategy_manager:
            strategy_manager.stop_all()
        if trading_engine:
            trading_engine.disconnect()
        if task_scheduler:
            task_scheduler.shutdown()
        logger.info("程序已退出")


if __name__ == "__main__":
    main()
