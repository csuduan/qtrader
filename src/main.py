"""
主程序入口
启动交易引擎、订单扫描器和API服务
"""
import asyncio
import signal
import sys
from threading import Thread
from time import sleep

import uvicorn

from src.api.app import create_app, websocket_manager
from src.config_loader import AppConfig, ensure_directories, load_config
from src.context import set_config, set_task_scheduler, set_trading_engine
from src.database import init_database
from src.persistence import init_persistence
from src.scheduler import TaskScheduler
from src.account_manager import AccountManager
from src.utils.logger import get_logger, setup_logger

logger = get_logger(__name__)

# 全局变量
config: AppConfig = None
account_manager = None
task_scheduler = TaskScheduler = None
running = False


def load_application_config() -> AppConfig:
    """加载应用配置"""
    try:
        cfg = load_config()
        ensure_directories(cfg)
        return cfg
    except FileNotFoundError as e:
        logger.error(f"配置文件不存在: {e}")
        logger.info("请创建 config/config.yaml 文件，可参考 config/config.example.yaml")
        sys.exit(1)
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        sys.exit(1)


def signal_handler(signum, frame):
    """信号处理器"""
    global running
    logger.info(f"收到信号 {signum}，准备退出...")
    running = False

    # 断开连接
    if account_manager:
        from src.account_manager import get_account_manager
        manager = get_account_manager()
        if manager:
            manager.shutdown_all()

    # 关闭任务调度器
    if task_scheduler:
        task_scheduler.shutdown()

    sys.exit(0)


def main():
    """主函数"""
    global config, account_manager, task_scheduler, running

    # 加载配置
    config = load_application_config()
    set_config(config)

    # 设置日志
    setup_logger(
        log_dir=config.paths.logs,
        log_level="INFO",
    )

    logger.info("=" * 60)
    logger.info("Q-Trader系统启动 - 多账户模式（单进程多线程）")
    logger.info("=" * 60)

    # 初始化数据库
    init_database(config.paths.database)

    # 启动数据持久化服务
    init_persistence()

    # 创建账户管理器并初始化所有账户
    logger.info("初始化账户管理器...")
    account_manager = AccountManager(config)
    account_manager.initialize_all()

    # 创建任务调度器
    logger.info("创建任务调度器...")
    task_scheduler = TaskScheduler(config, account_manager)
    task_scheduler.start()

    # 启动FastAPI应用
    app = create_app(config)
    logger.info(f"启动API服务，监听 {config.api.host}:{config.api.port}")
    logger.info(f"API文档: http://{config.api.host}:{config.api.port}/docs")
    logger.info(f"WebSocket: ws://{config.api.host}:{config.api.port}/ws")

    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


    try:
        uvicorn.run(
            app,
            host=config.api.host,
            port=config.api.port,
            log_level="info",
        )
    finally:
        # 关闭所有账户
        if account_manager:
            account_manager.shutdown_all()
        if task_scheduler:
            task_scheduler.shutdown()
        logger.info("程序已退出")


if __name__ == "__main__":
    main()
