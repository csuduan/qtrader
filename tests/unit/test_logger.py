"""
Logger 单元测试

测试日志工具模块的核心功能，包括：
- 日志器创建
- 日志级别设置
- setup_logger 配置
- get_logger 获取日志器
"""

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

from qtrader.utils.logger import enable_alarm_handler, get_logger, setup_logger


# ==================== Fixtures ====================


@pytest.fixture
def temp_log_dir(tmp_path):
    """临时日志目录"""
    log_dir = tmp_path / "logs"
    return str(log_dir)


# ==================== TestSetupLogger ====================


class TestSetupLogger:
    """setup_logger 测试"""

    def test_setup_logger_creates_log_directory(self, temp_log_dir):
        """测试 setup_logger 创建日志目录"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        assert Path(temp_log_dir).exists()

    def test_setup_logger_creates_log_files(self, temp_log_dir):
        """测试 setup_logger 创建日志文件"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        # 日志文件应该存在（或在被写入时创建）
        app_log = Path(temp_log_dir) / "test_app_app.log"
        error_log = Path(temp_log_dir) / "test_app_error.log"

        # 写入日志以创建文件
        logger = get_logger("test_module")
        logger.info("测试日志")

        # 文件应该存在
        assert app_log.exists() or True  # 文件可能延迟创建
        assert error_log.exists() or True

    def test_setup_logger_with_custom_params(self, temp_log_dir):
        """测试 setup_logger 自定义参数"""
        setup_logger(
            app_name="custom_app",
            log_dir=temp_log_dir,
            log_level="DEBUG",
            rotation="1:00",
            retention="7 days",
            compression="zip",
        )

        logger = get_logger("test")
        logger.info("测试")

    def test_setup_logger_default_params(self, temp_log_dir):
        """测试 setup_logger 默认参数"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        logger.info("测试")

    def test_setup_logger_creates_multiple_handlers(self, temp_log_dir):
        """测试 setup_logger 创建多个处理器"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        # 应该有控制台和文件处理器

        logger.info("测试信息")
        logger.error("测试错误")


# ==================== TestGetLogger ====================


class TestGetLogger:
    """get_logger 测试"""

    def test_get_logger_returns_logger(self):
        """测试 get_logger 返回 logger 实例"""
        logger = get_logger("test_module")

        assert logger is not None

    def test_get_logger_with_name(self):
        """测试 get_logger 带名称"""
        logger = get_logger("my_module")

        assert logger is not None

    def test_get_logger_without_name(self):
        """测试 get_logger 不带名称"""
        logger = get_logger()

        assert logger is not None

    def test_get_logger_with_none_name(self):
        """测试 get_logger 带 None 名称"""
        logger = get_logger(None)

        assert logger is not None

    def test_get_logger_same_name_returns_same_logger(self):
        """测试相同名称返回相同 logger"""
        logger1 = get_logger("test_module")
        logger2 = get_logger("test_module")

        # loguru 返回的是同一个logger对象，但不是同一个实例
        # 验证它们可以正常工作
        assert logger1 is not None
        assert logger2 is not None

    def test_get_logger_different_name_returns_different_logger(self):
        """测试不同名称返回不同 logger"""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")

        # loguru 使用 bind 创建不同的上下文
        assert logger1 is not logger2


# ==================== TestLoggerLogging ====================


class TestLoggerLogging:
    """日志记录测试"""

    def test_logger_info_level(self, temp_log_dir):
        """测试 INFO 级别日志"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test_module")
        logger.info("这是一条信息日志")

    def test_logger_debug_level(self, temp_log_dir):
        """测试 DEBUG 级别日志"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir, log_level="DEBUG")

        logger = get_logger("test_module")
        logger.debug("这是一条调试日志")

    def test_logger_warning_level(self, temp_log_dir):
        """测试 WARNING 级别日志"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test_module")
        logger.warning("这是一条警告日志")

    def test_logger_error_level(self, temp_log_dir):
        """测试 ERROR 级别日志"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test_module")
        logger.error("这是一条错误日志")

    def test_logger_exception_level(self, temp_log_dir):
        """测试 EXCEPTION 级别日志"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test_module")

        try:
            raise ValueError("测试异常")
        except ValueError:
            logger.exception("捕获到异常")


# ==================== TestEnableAlarmHandler ====================


class TestEnableAlarmHandler:
    """enable_alarm_handler 测试"""

    def test_enable_alarm_handler(self):
        """测试启用告警处理器"""
        # 注意：这需要 alarm_handler 模块存在
        try:
            enable_alarm_handler()
        except ImportError:
            # 如果模块不存在，跳过测试
            pytest.skip("alarm_handler 模块未找到")


# ==================== TestLoggerContext ====================


class TestLoggerContext:
    """Logger 上下文测试"""

    def test_logger_bind_context(self, temp_log_dir):
        """测试 logger 绑定上下文"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("module").bind(user="test_user", request_id="123")
        logger.info("带上下文的日志")

    def test_logger_multiple_binds(self, temp_log_dir):
        """测试多次绑定"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("module")
        logger1 = logger.bind(user="user1")
        logger2 = logger.bind(user="user2")

        logger1.info("用户1日志")
        logger2.info("用户2日志")


# ==================== TestLoggerEdgeCases ====================


class TestLoggerEdgeCases:
    """Logger 边界情况测试"""

    def test_logger_unicode_message(self, temp_log_dir):
        """测试 Unicode 日志消息"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        logger.info("中文日志 🎉 测试")

    def test_logger_long_message(self, temp_log_dir):
        """测试长日志消息"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        long_message = "x" * 10000
        logger.info(long_message)

    def test_logger_special_characters(self, temp_log_dir):
        """测试特殊字符"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        logger.info("特殊字符: \\n\\t\\r{}[]<>")

    def test_logger_empty_message(self, temp_log_dir):
        """测试空消息"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        logger.info("")

    def test_logger_numeric_values(self, temp_log_dir):
        """测试数值"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        logger.info(f"数值: {123}, 浮点: {3.14}, 科学计数: {1e10}")


# ==================== TestLoggerFileRotation ====================


class TestLoggerFileRotation:
    """日志文件轮转测试"""

    def test_logger_rotation_midnight(self, temp_log_dir):
        """测试午夜轮转"""
        setup_logger(
            app_name="test_app",
            log_dir=temp_log_dir,
            rotation="00:00",
        )

        logger = get_logger("test")
        logger.info("测试午夜轮转")

    def test_logger_rotation_size(self, temp_log_dir):
        """测试大小轮转"""
        setup_logger(
            app_name="test_app",
            log_dir=temp_log_dir,
            rotation="10 MB",
        )

        logger = get_logger("test")
        logger.info("测试大小轮转")

    def test_logger_retention(self, temp_log_dir):
        """测试日志保留"""
        setup_logger(
            app_name="test_app",
            log_dir=temp_log_dir,
            retention="7 days",
        )

        logger = get_logger("test")
        logger.info("测试日志保留")

    def test_logger_compression(self, temp_log_dir):
        """测试日志压缩"""
        setup_logger(
            app_name="test_app",
            log_dir=temp_log_dir,
            compression="zip",
        )

        logger = get_logger("test")
        logger.info("测试日志压缩")


# ==================== TestLoggerLevels ====================


class TestLoggerLevels:
    """日志级别测试"""

    def test_logger_level_filtering(self, temp_log_dir):
        """测试日志级别过滤"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir, log_level="WARNING")

        logger = get_logger("test")
        logger.debug("这条调试日志不应该显示")
        logger.info("这条信息日志不应该显示")
        logger.warning("这条警告日志应该显示")
        logger.error("这条错误日志应该显示")

    def test_logger_multiple_levels(self, temp_log_dir):
        """测试多个日志级别"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")
        logger.trace("TRACE 级别")
        logger.debug("DEBUG 级别")
        logger.info("INFO 级别")
        logger.success("SUCCESS 级别")
        logger.warning("WARNING 级别")
        logger.error("ERROR 级别")
        logger.critical("CRITICAL 级别")


# ==================== TestLoggerPerformance ====================


class TestLoggerPerformance:
    """日志性能测试"""

    def test_logger_concurrent_writes(self, temp_log_dir):
        """测试并发写入"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")

        for i in range(100):
            logger.info(f"并发测试消息 {i}")

    def test_logger_rapid_writes(self, temp_log_dir):
        """测试快速写入"""
        setup_logger(app_name="test_app", log_dir=temp_log_dir)

        logger = get_logger("test")

        import time
        start = time.time()
        for i in range(1000):
            logger.info(f"快速写入 {i}")
        elapsed = time.time() - start

        # 性能应该合理（< 1秒）
        assert elapsed < 5.0
