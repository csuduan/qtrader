"""
Socket通讯快速测试
"""
import asyncio
import sys
import os
import tempfile
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.ipc import SocketServer, SocketClient, request
from src.utils.logger import get_logger

logger = get_logger("quick_test")


class TestHandlers:
    @request("echo")
    async def handle_echo(self, data: dict):
        return {"received": data}


async def test_unknown_message_type():
    """测试未注册消息类型不会导致连接断开"""
    logger.info("=" * 60)
    logger.info("测试: 未注册消息类型处理")
    logger.info("=" * 60)

    socket_path = f"/tmp/test_quick_{os.getpid()}.sock"

    # 启动服务器
    server = SocketServer(socket_path, "test_account")
    handlers = TestHandlers()
    server.register_handlers_from_instance(handlers)
    await server.start()

    # 连接客户端
    client = SocketClient(socket_path, "test_account")
    connected = await client.connect(retry_interval=1, max_retries=5)
    assert connected, "客户端应该成功连接"

    try:
        # 1. 发送正常请求
        logger.info("发送正常echo请求...")
        response = await client.request("echo", {"message": "hello"}, timeout=5.0)
        assert response is not None, "正常请求应该有响应"
        logger.info(f"正常请求响应: {response}")

        # 2. 发送未注册的消息类型
        logger.info("发送未注册的消息类型...")
        try:
            response = await client.request("unknown_type", {"data": "test"}, timeout=5.0)
            logger.info(f"未注册类型响应: {response}")
        except Exception as e:
            logger.info(f"未注册类型返回异常（符合预期）: {e}")
        # 应该收到错误响应，而不是连接断开

        # 3. 再次发送正常请求，验证连接仍然有效
        logger.info("再次发送正常请求，验证连接...")
        response = await client.request("echo", {"message": "still alive"}, timeout=5.0)
        assert response is not None, "连接应该仍然有效"
        logger.info(f"第二次正常请求响应: {response}")

        logger.info("✓ 测试通过: 未注册消息类型不会导致连接断开")
        return True

    except Exception as e:
        logger.error(f"✗ 测试失败: {e}", exc_info=True)
        return False
    finally:
        await client.disconnect()
        await server.stop()
        try:
            os.unlink(socket_path)
        except:
            pass


async def test_server_error_response():
    """测试服务器内部错误返回错误响应而不是断开连接"""
    logger.info("=" * 60)
    logger.info("测试: 服务器内部错误处理")
    logger.info("=" * 60)

    socket_path = f"/tmp/test_error_{os.getpid()}.sock"

    # 启动服务器
    server = SocketServer(socket_path, "test_account")
    handlers = TestHandlers()
    server.register_handlers_from_instance(handlers)
    await server.start()

    # 连接客户端
    client = SocketClient(socket_path, "test_account")
    connected = await client.connect(retry_interval=1, max_retries=5)
    assert connected, "客户端应该成功连接"

    try:
        # 触发服务器错误
        logger.info("发送触发服务器错误的请求...")
        response = await client.request("trigger_error", {"data": "test"}, timeout=5.0)
        logger.info(f"服务器错误响应: {response}")

        # 验证收到错误响应
        assert response is not None, "应该收到错误响应"
        assert response.get("status") == "error", "应该返回错误状态"

        # 再次发送正常请求，验证连接仍然有效
        logger.info("再次发送正常请求，验证连接...")
        response = await client.request("echo", {"message": "connection OK"}, timeout=5.0)
        assert response is not None, "连接应该仍然有效"
        logger.info(f"正常请求响应: {response}")

        logger.info("✓ 测试通过: 服务器错误返回错误响应，连接保持")
        return True

    except Exception as e:
        logger.error(f"✗ 测试失败: {e}", exc_info=True)
        return False
    finally:
        await client.disconnect()
        await server.stop()
        try:
            os.unlink(socket_path)
        except:
            pass


async def main():
    """运行所有测试"""
    logger.info("\n" + "=" * 60)
    logger.info("Socket通讯测试开始")
    logger.info("=" * 60 + "\n")

    results = []

    # 测试1: 未注册消息类型
    result = await test_unknown_message_type()
    results.append(("未注册消息类型处理", result))

    # 测试2: 服务器内部错误
    result = await test_server_error_response()
    results.append(("服务器内部错误处理", result))

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
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("测试被中断")
        sys.exit(1)
