"""
账户控制接口测试
测试从 system.py 移动到 account.py 的接口：
- 启动账户Trader
- 停止账户Trader
- 连接账户网关
- 断开账户网关
- 暂停账户交易
- 恢复账户交易

client / mock_trading_manager 夹具来自 conftest.py（空 lifespan + 注入 mock + admin JWT）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestAccountTraderControl:
    """测试账户Trader启动/停止接口"""

    def test_start_trader_success(self, client, mock_trading_manager):
        """测试成功启动Trader"""
        account_id = "test_account"

        mock_trading_manager.start_trader = AsyncMock(return_value=True)

        response = client.post(f"/api/account/{account_id}/start")

        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert response.json()["data"]["running"] is True
        assert "Trader已启动" in response.json()["message"]

    def test_start_trader_failure(self, client, mock_trading_manager):
        """测试启动Trader失败"""
        account_id = "test_account"

        mock_trading_manager.start_trader = AsyncMock(return_value=False)

        response = client.post(f"/api/account/{account_id}/start")

        # error_response returns HTTP 400 with error code in body
        assert response.status_code == 400
        assert response.json()["code"] == 500
        assert "Trader启动失败" in response.json()["message"]

    def test_stop_trader_success(self, client, mock_trading_manager):
        """测试成功停止Trader"""
        account_id = "test_account"

        mock_trading_manager.stop_trader = AsyncMock(return_value=True)

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

        mock_trader = MagicMock()
        mock_trader.connect = AsyncMock(return_value=True)
        mock_trading_manager.traders = {account_id: mock_trader}

        response = client.post(f"/api/account/{account_id}/connect")

        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert response.json()["data"]["connected"] is True
        assert "连接成功" in response.json()["message"]

    def test_connect_gateway_failure(self, client, mock_trading_manager):
        """测试连接网关失败（trader.connect 返回 False）"""
        account_id = "test_account"

        mock_trader = MagicMock()
        mock_trader.connect = AsyncMock(return_value=False)
        mock_trading_manager.traders = {account_id: mock_trader}

        response = client.post(f"/api/account/{account_id}/connect")

        assert response.status_code == 400
        assert response.json()["code"] == 500
        assert "连接失败" in response.json()["message"]

    def test_disconnect_gateway_success(self, client, mock_trading_manager):
        """测试成功断开网关"""
        account_id = "test_account"

        mock_trader = MagicMock()
        mock_trader.disconnect = AsyncMock(return_value=True)
        mock_trading_manager.traders = {account_id: mock_trader}

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

        mock_trader = MagicMock()
        mock_trader.pause = AsyncMock(return_value=True)
        mock_trading_manager.traders = {account_id: mock_trader}

        response = client.post(f"/api/account/{account_id}/pause")

        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert response.json()["data"]["paused"] is True
        assert "交易已暂停" in response.json()["message"]

    def test_resume_trading_success(self, client, mock_trading_manager):
        """测试成功恢复交易"""
        account_id = "test_account"

        mock_trader = MagicMock()
        mock_trader.resume = AsyncMock(return_value=True)
        mock_trading_manager.traders = {account_id: mock_trader}

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

        response = client.post(f"/api/account/{account_id}/connect")

        # error_response returns HTTP 400 with error code in body
        assert response.status_code == 400
        assert response.json()["code"] == 404
        assert "不存在" in response.json()["message"]

    def test_pause_trading_trader_not_found(self, client, mock_trading_manager):
        """测试暂停交易时账户不存在"""
        account_id = "test_account"
        mock_trading_manager.traders = {}

        response = client.post(f"/api/account/{account_id}/pause")

        # error_response returns HTTP 400 with error code in body
        assert response.status_code == 400
        assert response.json()["code"] == 404
        assert "不存在" in response.json()["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
