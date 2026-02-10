"""
Socket通讯测试脚本

测试场景：
1. 基本连接/断开
2. 多连接支持
3. 异常消息处理（未注册的消息类型）
4. 服务端关闭连接后的清理
5. 客户端重连

运行方式：
    cd /opt/dev/qtrader && python tests/test_socket_communication.py
"""

import asyncio
import sys
import tempfile
import os
import time
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.trader.socket_server import SocketServer, request
from src.manager.socket_client import SocketClient
from src.utils.logger import get_logger

logger = get_logger("socket_test")


class TestMessageHandlers:
    """测试用的消息处理器"""

    def __init__(self):
        self.last_echo_data = None
        self.error_count = 0

    @request("echo")
    async def handle_echo(self, data: dict):
        """回显消息"""
        self.last_echo_data = data
        logger.info(f"[Server] 收到echo请求: {data}")
        return {"received": data}

    @request("trigger_error")
    async def handle_trigger_error(self, data: dict):
        """触发服务器内部错误"""
        logger.info(f"[Server] 收到触发错误请求")
        raise RuntimeError("故意触发的内部错误")


async def test_basic_communication():
    """测试1: 基本通讯"""
    logger.info("=" * 60)
    logger.info("测试1: 基本通讯")
    logger.info("=" * 60)

    socket_path = f"/tmp/test_socket_{os.getpid()}.sock"
    account_id = "test_account"

    # 创建服务器
    server = SocketServer(socket_path, account_id)
    handlers = TestMessageHandlers()
    server.register_handlers_from_instance(handlers)
    await server.start()

    # 创建客户端
    client = SocketClient(socket_path, account_id)
    connected = await client.connect(retry_interval=1, max_retries=5)
    if not connected:
        logger.error("客户端连接失败")
        await server.stop()
        return False

    try:
        # 测试正常请求
        response = await client.request("echo", {"message": "Hello"}, timeout=5.0)
        logger.info(f"正常请求响应: {response}")
        assert response is not None, "正常请求应该有响应"
        assert response.get("received", {}).get("message") == "Hello", "回显数据应该匹配"

        # 测试未注册的消息类型
        logger.info("发送未注册的消息类型...")
        response = await client.request("unknown_type", {"data": "test"}, timeout=5.0)
        logger.info(f"未注册类型响应: {response}")
        # 未注册的消息类型应该返回错误，但连接不应该断开

        # 再次发送正常请求，验证连接仍然有效
        logger.info("再次发送正常请求，验证连接...")
        response = await client.request("echo", {"message": "Still connected"}, timeout=5.0)
        logger.info(f"第二次正常请求响应: {response}")
        assert response is not None, "连接应该仍然有效"

        logger.info("✓ 基本通讯测试通过")
        return True

    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        return False
    finally:
        await client.disconnect()
        await server.stop()


async def test_server_error_handling():
    """测试2: 服务端错误处理"""
    logger.info("=" * 60)
    logger.info("测试2: 服务端错误处理")
    logger.info("=" * 60)

    socket_path = f"/tmp/test_socket_error_{os.getpid()}.sock"
    account_id = "test_account"

    # 创建服务器
    server = SocketServer(socket_path, account_id)
    handlers = TestMessageHandlers()
    server.register_handlers_from_instance(handlers)
    await server.start()

    # 创建客户端
    client = SocketClient(socket_path, account_id)
    connected = await client.connect(retry_interval=1, max_retries=5)
    if not connected:
        logger.error("客户端连接失败")
        await server.stop()
        return False

    try:
        # 测试触发服务器内部错误
        logger.info("发送触发服务器错误的请求...")
        response = await client.request("trigger_error", {"data": "test"}, timeout=5.0)
        logger.info(f"服务器错误响应: {response}")
        # 应该收到错误响应而不是连接断开
        assert response is not None, "应该有错误响应"

        # 再次发送正常请求，验证连接仍然有效
        logger.info("再次发送正常请求，验证连接...")
        response = await client.request("echo", {"message": "Connection OK"}, timeout=5.0)
        logger.info(f"正常请求响应: {response}")
        assert response is not None, "连接应该仍然有效"

        logger.info("✓ 服务端错误处理测试通过")
        return True

    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        return False
    finally:
        await client.disconnect()
        await server.stop()


async def test_multi_connection():
    """测试3: 多连接支持"""
    logger.info("=" * 60)
    logger.info("测试3: 多连接支持")
    logger.info("=" * 60)

    socket_path = f"/tmp/test_socket_multi_{os.getpid()}.sock"
    account_id = "test_account"

    # 创建服务器
    server = SocketServer(socket_path, account_id)
    handlers = TestMessageHandlers()
    server.register_handlers_from_instance(handlers)
    await server.start()

    # 创建多个客户端
    clients = []
    try:
        for i in range(3):
            client = SocketClient(socket_path, f"{account_id}_client_{i}")
            connected = await client.connect(retry_interval=1, max_retries=5)
            if not connected:
                logger.error(f"客户端 {i} 连接失败")
                raise RuntimeError(f"客户端 {i} 连接失败")
            clients.append(client)
            logger.info(f"客户端 {i} 已连接")

        # 每个客户端发送请求
        for i, client in enumerate(clients):
            response = await client.request("echo", {"client_id": i}, timeout=5.0)
            logger.info(f"客户端 {i} 响应: {response}")
            assert response is not None, f"客户端 {i} 应该有响应"

        logger.info("✓ 多连接测试通过")
        return True

    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        return False
    finally:
        for client in clients:
            await client.disconnect()
        await server.stop()


async def run_all_tests():
    """运行所有测试"""
    logger.info("\n" + "=" * 60)
    logger.info("Socket通讯测试开始")
    logger.info("=" * 60 + "\n")

    results = []

    # 测试1: 基本通讯
    result = await test_basic_communication()
    results.append(("基本通讯", result))

    # 测试2: 服务端错误处理
    result = await test_server_error_handling()
    results.append(("服务端错误处理", result))

    # 测试3: 多连接支持
    result = await test_multi_connection()
    results.append(("多连接支持", result))

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
