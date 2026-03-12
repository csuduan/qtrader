#!/usr/bin/env python3
"""
SocketServer 异常测试

验证：
1. 单个请求异常不会导致 socket_server 不可用
2. 连续多个请求异常后，socket_server 仍能处理新请求
3. 异常请求不会影响到其他连接
"""

import asyncio
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.ipc import SocketServer, SocketClient, request
from src.utils.logger import get_logger

logger = get_logger("socket_exception_test")


class TestException(Exception):
    """测试用异常"""
    pass


class TestHandlers:
    """测试处理器"""

    def __init__(self):
        self.request_count = 0
        self.error_count = 0

    @request("normal")
    async def handle_normal(self, data: dict):
        """正常处理"""
        self.request_count += 1
        return {"status": "ok", "received": data}

    @request("error")
    async def handle_error(self, data: dict):
        """抛出异常"""
        self.request_count += 1
        self.error_count += 1
        raise TestException(f"故意抛出的异常: {data}")

    @request("error_once")
    async def handle_error_once(self, data: dict):
        """第一次抛出异常，之后正常"""
        self.request_count += 1
        if self.error_count == 0:
            self.error_count += 1
            raise TestException("第一次请求异常")
        return {"status": "ok_after_error", "received": data}


async def test_single_error_not_affect_server():
    """测试1: 单个异常请求不会导致服务器不可用"""
    logger.info("=" * 60)
    logger.info("测试1: 单个异常请求不会导致服务器不可用")
    logger.info("=" * 60)

    socket_path = f"/tmp/test_socket_server_{os.getpid()}.sock"
    account_id = "test_account"

    # 创建并启动服务器
    server = SocketServer(socket_path, account_id)
    handlers = TestHandlers()
    server.register_handlers_from_instance(handlers)
    await server.start()

    # 创建客户端
    client = SocketClient(socket_path, account_id)
    connected = await client.connect(retry_interval=1, max_retries=5)
    assert connected, "客户端应该成功连接"

    try:
        # 1. 发送正常请求
        logger.info("步骤1: 发送正常请求...")
        response = await client.request("normal", {"step": 1}, timeout=5.0)
        logger.info(f"正常请求响应: {response}")
        assert response is not None, "正常请求应该有响应"
        assert response.get("status") == "ok", "正常请求应该成功"

        # 2. 发送会抛出异常的请求
        logger.info("步骤2: 发送会抛出异常的请求...")
        try:
            response = await client.request("error", {"step": 2}, timeout=5.0)
            # 如果服务器正确处理异常，应该返回错误响应
            logger.info(f"异常请求响应: {response}")
        except Exception as e:
            logger.info(f"异常请求抛出异常（预期行为）: {e}")

        # 3. 再次发送正常请求，验证服务器仍然可用
        logger.info("步骤3: 异常请求后再次发送正常请求...")
        response = await client.request("normal", {"step": 3}, timeout=5.0)
        logger.info(f"异常后正常请求响应: {response}")
        assert response is not None, "异常后正常请求应该有响应"
        assert response.get("status") == "ok", "异常后正常请求应该成功"

        logger.info("✓ 测试1通过: 单个异常请求不会导致服务器不可用")
        return True

    except Exception as e:
        logger.error(f"✗ 测试1失败: {e}", exc_info=True)
        return False
    finally:
        await client.disconnect()
        await server.stop()
        try:
            os.unlink(socket_path)
        except:
            pass


async def test_consecutive_errors():
    """测试2: 连续多个异常请求后，服务器仍能处理新请求"""
    logger.info("=" * 60)
    logger.info("测试2: 连续多个异常请求后服务器仍可用")
    logger.info("=" * 60)

    socket_path = f"/tmp/test_socket_server2_{os.getpid()}.sock"
    account_id = "test_account"

    server = SocketServer(socket_path, account_id)
    handlers = TestHandlers()
    server.register_handlers_from_instance(handlers)
    await server.start()

    client = SocketClient(socket_path, account_id)
    connected = await client.connect(retry_interval=1, max_retries=5)
    assert connected, "客户端应该成功连接"

    try:
        error_count = 0
        # 连续发送10个会抛出异常的请求
        logger.info("连续发送10个异常请求...")
        for i in range(10):
            try:
                await client.request("error", {"index": i}, timeout=2.0)
            except Exception as e:
                error_count += 1
                logger.debug(f"第{i+1}个异常请求失败: {e}")

        logger.info(f"10个异常请求完成，失败次数: {error_count}")

        # 验证服务器仍然可用
        logger.info("异常请求后发送正常请求验证...")
        response = await client.request("normal", {"test": "after_errors"}, timeout=5.0)
        assert response is not None, "服务器应该仍然可用"
        assert response.get("status") == "ok", "请求应该成功"

        logger.info("✓ 测试2通过: 连续异常请求后服务器仍然可用")
        return True

    except Exception as e:
        logger.error(f"✗ 测试2失败: {e}", exc_info=True)
        return False
    finally:
        await client.disconnect()
        await server.stop()
        try:
            os.unlink(socket_path)
        except:
            pass


async def run_all_tests():
    """运行所有测试"""
    logger.info("\n" + "=" * 60)
    logger.info("SocketServer 异常测试开始")
    logger.info("=" * 60 + "\n")

    results = []

    # 测试1: 单个异常请求
    result = await test_single_error_not_affect_server()
    results.append(("单个异常请求", result))

    # 测试2: 连续多个异常请求
    result = await test_consecutive_errors()
    results.append(("连续多个异常请求", result))

    # 输出测试结果汇总
    logger.info("\n" + "=" * 60)
    logger.info("测试结果汇总")
    logger.info("=" * 60)
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        logger.info(f"{name}: {status}")
    logger.info("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)
    logger.info(f"总计: {passed}/{total} 通过")

    return all(r for _, r in results)


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("测试被中断")
        sys.exit(1)
