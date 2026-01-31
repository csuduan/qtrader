"""
账户控制接口测试
测试从 system.py 移动到 account.py 的接口：
- 启动账户Trader
- 停止账户Trader
- 连接账户网关
- 断开账户网关
- 暂停账户交易
- 恢复账户交易
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from src.manager.app import create_app
from src.manager.core.trading_manager import TradingManager


@pytest.fixture
def app():
    """创建测试应用"""
    return create_app()


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def mock_trading_manager():
    """模拟 TradingManager"""
    mock = MagicMock(spec=TradingManager)
    mock.traders = {}
    return mock


class TestAccountTraderControl:
    """测试账户Trader启动/停止接口"""

    def test_start_trader_success(self, client, mock_trading_manager):
        """测试成功启动Trader"""
        account_id = "test_account"

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            mock_trading_manager.start_trader = MagicMock(return_value=True)

            response = client.post(f"/api/account/{account_id}/start")

            assert response.status_code == 200
            assert response.json()["code"] == 0
            assert response.json()["data"]["running"] is True
            assert "Trader已启动" in response.json()["message"]

    def test_start_trader_failure(self, client, mock_trading_manager):
        """测试启动Trader失败"""
        account_id = "test_account"

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            mock_trading_manager.start_trader = MagicMock(return_value=False)

            response = client.post(f"/api/account/{account_id}/start")

            assert response.status_code == 200
            assert response.json()["code"] == 500
            assert "Trader启动失败" in response.json()["message"]

    def test_stop_trader_success(self, client, mock_trading_manager):
        """测试成功停止Trader"""
        account_id = "test_account"

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            mock_trading_manager.stop_trader = MagicMock(return_value=True)

            response = client.post(f"/api/account/{account_id}/stop")

            assert response.status_code == 200
            assert response.json()["code"] == 0
            assert response.json()["data"]["running"] is False
            assert "Trader已停止" in response.json()["message"]


class TestAccountGatewayControl:
    """测试账户网关连接/断开接口"""

    def test_connect_gateway_success(self, client, mock_trading_manager):
        """测试成功连接网关"""
        account_id = "test_account"

        # 创建 mock trader
        mock_trader = MagicMock()
        mock_trading_manager.traders = {account_id: mock_trader}

        # 创建 mock engine
        mock_engine = MagicMock()
        mock_engine.gateway.connected = False
        mock_engine.connect = MagicMock(return_value=True)
        mock_trading_manager.get_trading_engine = MagicMock(return_value=mock_engine)

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            response = client.post(f"/api/account/{account_id}/connect")

            assert response.status_code == 200
            assert response.json()["code"] == 0
            assert response.json()["data"]["connected"] is True
            assert "连接成功" in response.json()["message"]

    def test_connect_gateway_already_connected(self, client, mock_trading_manager):
        """测试连接已连接的网关"""
        account_id = "test_account"

        # 创建 mock trader
        mock_trader = MagicMock()
        mock_trading_manager.traders = {account_id: mock_trader}

        # 创建 mock engine (已连接)
        mock_engine = MagicMock()
        mock_engine.gateway.connected = True
        mock_trading_manager.get_trading_engine = MagicMock(return_value=mock_engine)

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            response = client.post(f"/api/account/{account_id}/connect")

            assert response.status_code == 200
            assert response.json()["code"] == 0
            assert response.json()["data"]["connected"] is True
            assert "已连接" in response.json()["message"]

    def test_disconnect_gateway_success(self, client, mock_trading_manager):
        """测试成功断开网关"""
        account_id = "test_account"

        # 创建 mock trader
        mock_trader = MagicMock()
        mock_trading_manager.traders = {account_id: mock_trader}

        # 创建 mock engine
        mock_engine = MagicMock()
        mock_engine.disconnect = MagicMock()
        mock_trading_manager.get_trading_engine = MagicMock(return_value=mock_engine)

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            response = client.post(f"/api/account/{account_id}/disconnect")

            assert response.status_code == 200
            assert response.json()["code"] == 0
            assert response.json()["data"]["connected"] is False
            assert "已断开连接" in response.json()["message"]


class TestAccountTradingControl:
    """测试账户交易暂停/恢复接口"""

    def test_pause_trading_success(self, client, mock_trading_manager):
        """测试成功暂停交易"""
        account_id = "test_account"

        # 创建 mock engine
        mock_engine = MagicMock()
        mock_engine.pause = MagicMock()
        mock_trading_manager.get_trading_engine = MagicMock(return_value=mock_engine)

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            response = client.post(f"/api/account/{account_id}/pause")

            assert response.status_code == 200
            assert response.json()["code"] == 0
            assert response.json()["data"]["paused"] is True
            assert "交易已暂停" in response.json()["message"]

    def test_resume_trading_success(self, client, mock_trading_manager):
        """测试成功恢复交易"""
        account_id = "test_account"

        # 创建 mock engine
        mock_engine = MagicMock()
        mock_engine.resume = MagicMock()
        mock_trading_manager.get_trading_engine = MagicMock(return_value=mock_engine)

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            response = client.post(f"/api/account/{account_id}/resume")

            assert response.status_code == 200
            assert response.json()["code"] == 0
            assert response.json()["data"]["paused"] is False
            assert "交易已恢复" in response.json()["message"]


class TestErrorHandling:
    """测试错误处理"""

    def test_connect_gateway_trader_not_found(self, client, mock_trading_manager):
        """测试连接网关时trader不存在"""
        account_id = "non_existent_account"
        mock_trading_manager.traders = {}

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            response = client.post(f"/api/account/{account_id}/connect")

            assert response.status_code == 200
            assert response.json()["code"] == 404
            assert "不存在" in response.json()["message"]

    def test_pause_trading_engine_not_initialized(self, client, mock_trading_manager):
        """测试暂停交易时引擎未初始化"""
        account_id = "test_account"
        mock_trading_manager.get_trading_engine = MagicMock(return_value=None)

        with patch('src.manager.api.routes.account.get_trading_manager', return_value=mock_trading_manager):
            response = client.post(f"/api/account/{account_id}/pause")

            assert response.status_code == 200
            assert response.json()["code"] == 500
            assert "交易引擎未初始化" in response.json()["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
