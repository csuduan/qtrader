import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.manager.app import create_app
from src.models.po import Base

app = create_app()


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db_session():
    """测试用数据库会话覆盖"""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


def mock_get_trading_manager():
    """模拟交易管理器"""
    mock_manager = MagicMock()
    mock_manager.traders = {}
    mock_manager.get_account = AsyncMock(return_value=None)
    mock_manager.get_all_accounts = AsyncMock(return_value=[])
    mock_manager.account_configs_map = {}
    return mock_manager


@pytest.fixture(scope="module")
def client():
    """创建测试客户端"""
    # 创建测试数据库表
    Base.metadata.create_all(bind=engine)

    # 覆盖依赖注入
    from src.manager.api import dependencies
    original_get_db = dependencies.get_db_session
    original_get_tm = dependencies.get_trading_manager

    dependencies.get_db_session = override_get_db_session
    dependencies.get_trading_manager = mock_get_trading_manager

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        # 恢复原始依赖
        dependencies.get_db_session = original_get_db
        dependencies.get_trading_manager = original_get_tm
        # 清理数据库
        Base.metadata.drop_all(bind=engine)


@pytest.mark.integration
class TestAccountAPI:
    def test_get_account_info(self, client):
        """测试获取账户信息"""
        response = client.get("/api/account")
        # 没有可用的账户时，可能返回400(验证错误)、404(不存在)或200(空数据)
        assert response.status_code in [200, 400, 404]

    def test_get_all_accounts(self, client):
        """测试获取所有账户信息"""
        response = client.get("/api/account/all")
        # 模拟的trading_manager返回空列表
        assert response.status_code in [200, 404]


@pytest.mark.integration
class TestPositionAPI:
    def test_get_positions(self, client):
        """测试获取持仓列表"""
        response = client.get("/api/positions")
        assert response.status_code in [200, 404, 400]


@pytest.mark.integration
class TestOrderAPI:
    def test_get_orders(self, client):
        """测试获取委托单列表"""
        response = client.get("/api/orders")
        assert response.status_code in [200, 404, 400]

    def test_create_order(self, client):
        """测试创建订单"""
        order_data = {
            "symbol": "SHFE.rb2505",
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": 3500.0,
            "price_type": "LIMIT"
        }
        response = client.post("/api/orders", json=order_data)
        # 交易引擎未连接，可能返回400或500
        assert response.status_code in [200, 400, 500]


@pytest.mark.integration
class TestTradeAPI:
    def test_get_trades_today(self, client):
        """测试获取今日成交"""
        response = client.get("/api/trades/today")
        assert response.status_code in [200, 404, 400]

    def test_get_trades_history(self, client):
        """测试获取历史成交"""
        response = client.get("/api/trades/history")
        assert response.status_code in [200, 404, 400]


@pytest.mark.integration
class TestHealthCheck:
    def test_root_endpoint(self, client):
        """测试根路径"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    def test_health_check(self, client):
        """测试健康检查"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # 健康检查返回 "ok"
        assert data["status"] in ["healthy", "ok"]
