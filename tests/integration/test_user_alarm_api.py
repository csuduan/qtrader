"""
用户管理与告警 API 集成测试

覆盖路由模块：
- qtrader.manager.api.routes.user（/api/admin/users，require_admin + DB 会话）
- qtrader.manager.api.routes.alarm（/api/alarm，app.state.db + AppContext 告警服务）

数据来源均以 _FakeDb/_FakeSession 替换（不连真实 PostgreSQL），
AppContext 中的告警服务用 MagicMock 注入并在用例结束后清理。

client / anon_client / mock_trading_manager 夹具来自 conftest.py。
"""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from qtrader.app_context import AppContext, get_app_context
from qtrader.manager.api.routes.auth import create_access_token
from qtrader.models.po import AlarmPo, UserPo

# conftest 中 admin token 的 sub（create_access_token("itest_admin", "admin")）
ADMIN_USER_ID = "itest_admin"


# ============ 数据库替身（模拟 SQLAlchemy 会话链式调用） ============


class _FakeExecResult:
    """模拟 session.execute() 返回值：支持 scalars().all() 与 scalar_one_or_none()"""

    def __init__(self, scalars_all=None, scalar_one=None):
        self._scalars_all = scalars_all if scalars_all is not None else []
        self._scalar_one = scalar_one

    def scalars(self):
        return self

    def all(self):
        return self._scalars_all

    def scalar_one_or_none(self):
        return self._scalar_one


class _FakeQuery:
    """模拟 SQLAlchemy Query：filter/order_by 返回自身以适配任意链长"""

    def __init__(self, items=None, first=None, scalar=0, update_count=0):
        self.items = items if items is not None else []
        self.first_result = first
        self.scalar_result = scalar
        self.update_result = update_count
        self.filters: list = []
        self.update_values: dict | None = None

    def filter(self, *criteria):
        self.filters.append(criteria)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.items

    def first(self):
        return self.first_result

    def scalar(self):
        return self.scalar_result

    def update(self, values, synchronize_session=False):
        self.update_values = values
        return self.update_result


class _FakeSession:
    """模拟 SQLAlchemy Session：execute 结果按调用顺序依次消费"""

    def __init__(self, query: _FakeQuery | None = None):
        self.query_obj = query or _FakeQuery()
        self.exec_results: list[_FakeExecResult] = []
        self.added: list = []
        self.deleted: list = []
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    def query(self, *entities):
        return self.query_obj

    def execute(self, stmt):
        assert self.exec_results, "测试未预期的 session.execute 调用"
        return self.exec_results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


class _FakeDb:
    """模拟 Database：get_session 上下文管理器 + get_session_sync"""

    def __init__(self, session: _FakeSession):
        self.session = session
        self.get_session_calls = 0
        self.get_session_sync_calls = 0

    @contextmanager
    def get_session(self):
        self.get_session_calls += 1
        yield self.session

    def get_session_sync(self):
        self.get_session_sync_calls += 1
        return self.session


# ============ 数据构造 ============


def make_user(user_id: str = "trader001", role: str = "trader", is_active: bool = True) -> UserPo:
    """构造持久化用户对象"""
    return UserPo(
        user_id=user_id,
        password="pbkdf2_sha256$100000$deadbeef$cafebabe",
        role=role,
        is_active=is_active,
        created_at=datetime(2026, 8, 1, 9, 0, 0),
        updated_at=datetime(2026, 8, 2, 9, 0, 0),
    )


def make_alarm(alarm_id: int = 1, account_id: str = "DQ", status: str = "UNCONFIRMED") -> AlarmPo:
    """构造持久化告警对象"""
    return AlarmPo(
        id=alarm_id,
        account_id=account_id,
        alarm_type="exception",
        indicator="1min",
        alarm_date="2026-09-01",
        alarm_time="10:30:00",
        source="risk",
        title="风险度告警",
        detail="风险度超过阈值",
        status=status,
        created_at=datetime(2026, 9, 1, 10, 30, 0),
    )


# ============ 夹具 ============


@pytest.fixture
def user_db(client):
    """将 user 路由的 get_database() 替换为 FakeDb，返回可检视的 db/session"""
    session = _FakeSession()
    db = _FakeDb(session)
    with patch("qtrader.manager.api.routes.user.get_database", return_value=db):
        yield SimpleNamespace(db=db, session=session)


@pytest.fixture
def alarm_db(client):
    """将 alarm 路由读取的 app.state.db 替换为 FakeDb"""
    session = _FakeSession()
    db = _FakeDb(session)
    client.app.state.db = db
    yield SimpleNamespace(db=db, session=session, query=session.query_obj)


@pytest.fixture
def alarm_service():
    """向 AppContext 注入 mock 告警服务，用例结束后清理"""
    svc = MagicMock()
    ctx = get_app_context()
    ctx.set(AppContext.KEY_ALARM_SERVICE, svc)
    yield svc
    ctx.remove(AppContext.KEY_ALARM_SERVICE)


def _trader_headers() -> dict:
    """构造 trader（非管理员）角色的请求头，覆盖 client 默认的 admin 头"""
    return {"Authorization": f"Bearer {create_access_token('trader001', 'trader')}"}


# ============ 用户管理 API ============


@pytest.mark.integration
class TestUserListAPI:
    """用户列表端点（GET /api/admin/users）"""

    def test_list_users(self, client, user_db):
        user_db.session.exec_results = [
            _FakeExecResult(scalars_all=[make_user("admin001", "admin"), make_user("trader001")])
        ]

        resp = client.get("/api/admin/users")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        assert body["data"][0]["user_id"] == "admin001"
        # user_id 同时作为 username 返回
        assert body["data"][0]["username"] == "admin001"
        assert body["data"][0]["role"] == "admin"
        assert body["data"][0]["is_active"] is True
        assert body["data"][0]["created_at"] == "2026-08-01T09:00:00"

    def test_list_users_requires_admin_role(self, client):
        resp = client.get("/api/admin/users", headers=_trader_headers())

        # require_admin 抛出的 403 经 http_exception_handler 包装为 HTTP 400 + 业务码 403
        assert resp.status_code == 400
        assert resp.json()["code"] == 403
        assert "管理员" in resp.json()["message"]

    def test_list_users_no_token_401(self, anon_client):
        resp = anon_client.get("/api/admin/users")
        assert resp.status_code == 401


@pytest.mark.integration
class TestUserCreateAPI:
    """创建用户端点（POST /api/admin/users）"""

    def test_create_user_success(self, client, user_db):
        user_db.session.exec_results = [_FakeExecResult(scalar_one=None)]

        resp = client.post(
            "/api/admin/users",
            json={"username": "newuser", "password": "secret123", "role": "trader"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "用户已创建"
        assert body["data"]["user_id"] == "newuser"
        assert body["data"]["username"] == "newuser"
        assert body["data"]["role"] == "trader"
        assert body["data"]["is_active"] is True

        # 落库对象使用 PBKDF2 哈希，绝不保存明文
        assert len(user_db.session.added) == 1
        saved = user_db.session.added[0]
        assert saved.user_id == "newuser"
        assert saved.role == "trader"
        assert saved.password.startswith("pbkdf2_sha256$")
        assert "secret123" not in saved.password
        assert user_db.session.commit_count == 1

    def test_create_user_duplicate_name(self, client, user_db):
        user_db.session.exec_results = [_FakeExecResult(scalar_one=make_user("newuser"))]

        resp = client.post(
            "/api/admin/users",
            json={"username": "newuser", "password": "secret123", "role": "trader"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 4001
        assert "用户名已存在" in resp.json()["message"]
        assert user_db.session.added == []

    def test_create_user_invalid_role(self, client, user_db):
        user_db.session.exec_results = [_FakeExecResult(scalar_one=None)]

        resp = client.post(
            "/api/admin/users",
            json={"username": "newuser", "password": "secret123", "role": "superuser"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 4002
        assert "无效的角色" in resp.json()["message"]
        assert user_db.session.added == []

    def test_create_user_short_password_rejected(self, client):
        """密码长度校验（Pydantic min_length=6）"""
        resp = client.post(
            "/api/admin/users", json={"username": "newuser", "password": "123", "role": "trader"}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 400


@pytest.mark.integration
class TestUserUpdateAPI:
    """更新用户端点（PUT /api/admin/users/{user_id}）"""

    def test_update_user_password(self, client, user_db):
        user = make_user("trader001")
        user_db.session.exec_results = [_FakeExecResult(scalar_one=user)]

        resp = client.put("/api/admin/users/trader001", json={"password": "newpass456"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "用户已更新"
        # 密码被重新哈希为 PBKDF2，且不含明文
        assert user.password.startswith("pbkdf2_sha256$")
        assert "newpass456" not in user.password
        assert user_db.session.commit_count == 1

    def test_update_user_role(self, client, user_db):
        user = make_user("trader001", role="trader")
        user_db.session.exec_results = [_FakeExecResult(scalar_one=user)]

        resp = client.put("/api/admin/users/trader001", json={"role": "guest"})

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert user.role == "guest"

    def test_update_user_invalid_role(self, client, user_db):
        user_db.session.exec_results = [_FakeExecResult(scalar_one=make_user("trader001"))]

        resp = client.put("/api/admin/users/trader001", json={"role": "hacker"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 4002

    def test_update_user_not_found(self, client, user_db):
        user_db.session.exec_results = [_FakeExecResult(scalar_one=None)]

        resp = client.put("/api/admin/users/ghost", json={"role": "guest"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404
        assert "用户不存在" in resp.json()["message"]

    def test_update_user_cannot_change_own_role(self, client, user_db):
        """管理员不能修改自己的角色（防止自我降级）"""
        admin = make_user(ADMIN_USER_ID, role="admin")
        user_db.session.exec_results = [_FakeExecResult(scalar_one=admin)]

        resp = client.put(f"/api/admin/users/{ADMIN_USER_ID}", json={"role": "guest"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 403
        assert "不能修改自己的角色" in resp.json()["message"]
        assert admin.role == "admin"
        assert user_db.session.commit_count == 0

    def test_update_user_rename_conflict(self, client, user_db):
        """改名为已存在的用户名被拒绝"""
        user_db.session.exec_results = [
            _FakeExecResult(scalar_one=make_user("trader001")),
            _FakeExecResult(scalar_one=make_user("trader002")),
        ]

        resp = client.put("/api/admin/users/trader001", json={"username": "trader002"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 4001
        assert "用户名已存在" in resp.json()["message"]


@pytest.mark.integration
class TestUserDeleteAPI:
    """删除用户端点（DELETE /api/admin/users/{user_id}）"""

    def test_delete_user_success(self, client, user_db):
        user = make_user("trader001")
        user_db.session.exec_results = [_FakeExecResult(scalar_one=user)]

        resp = client.delete("/api/admin/users/trader001")

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["message"] == "用户已删除"
        assert user_db.session.deleted == [user]
        assert user_db.session.commit_count == 1

    def test_delete_user_not_found(self, client, user_db):
        user_db.session.exec_results = [_FakeExecResult(scalar_one=None)]

        resp = client.delete("/api/admin/users/ghost")

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_delete_self_forbidden(self, client, user_db):
        """不能删除当前登录用户，且不触碰数据库"""
        resp = client.delete(f"/api/admin/users/{ADMIN_USER_ID}")

        assert resp.status_code == 400
        assert resp.json()["code"] == 403
        assert "不能删除当前登录用户" in resp.json()["message"]
        assert user_db.db.get_session_calls == 0


# ============ 告警 API ============


@pytest.mark.integration
class TestAlarmListAPI:
    """告警列表端点（GET /api/alarm/list）"""

    def test_list_today_alarms(self, client, alarm_db):
        alarm_db.query.items = [make_alarm(1), make_alarm(2, status="CONFIRMED")]

        resp = client.get("/api/alarm/list")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        assert body["data"][0]["id"] == 1
        assert body["data"][0]["account_id"] == "DQ"
        assert body["data"][0]["status"] == "UNCONFIRMED"
        assert body["data"][0]["created_at"] == "2026-09-01T10:30:00"
        assert alarm_db.session.closed is True

    def test_list_alarms_applies_filters(self, client, alarm_db):
        """account_id 与 status_filter 均转化为查询过滤条件"""
        alarm_db.query.items = []

        resp = client.get(
            "/api/alarm/list", params={"account_id": "DQ", "status_filter": "UNCONFIRMED"}
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        # 基础日期过滤 + 账户过滤 + 状态过滤
        assert len(alarm_db.query.filters) == 3

    def test_list_alarms_db_error(self, client, alarm_db):
        alarm_db.session.query_obj = None  # 触发链式调用异常

        resp = client.get("/api/alarm/list")

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "获取告警列表失败" in resp.json()["message"]


@pytest.mark.integration
class TestAlarmStatsAPI:
    """告警统计端点（GET /api/alarm/stats）"""

    def test_stats_counts(self, client, alarm_db):
        alarm_db.query.scalar_result = 7

        resp = client.get("/api/alarm/stats", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["today_total"] == 7
        assert data["unconfirmed"] == 7
        assert data["last_hour"] == 7
        assert data["last_five_minutes"] == 7
        assert alarm_db.session.closed is True

    def test_stats_db_error(self, client, alarm_db):
        alarm_db.session.query_obj = None

        resp = client.get("/api/alarm/stats")

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "获取告警统计失败" in resp.json()["message"]


@pytest.mark.integration
class TestAlarmConfirmAPI:
    """告警确认端点（POST /api/alarm/confirm/{alarm_id}）"""

    def test_confirm_alarm(self, client, alarm_db):
        alarm = make_alarm(3)
        alarm_db.query.first_result = alarm

        resp = client.post("/api/alarm/confirm/3", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "确认成功"
        assert alarm.status == "CONFIRMED"
        assert alarm_db.session.commit_count == 1

    def test_confirm_alarm_not_found(self, client, alarm_db):
        alarm_db.query.first_result = None

        resp = client.post("/api/alarm/confirm/99", json={})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404
        assert "告警不存在" in resp.json()["message"]

    def test_confirm_alarm_invalid_id(self, client):
        resp = client.post("/api/alarm/confirm/not-an-int", json={})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400


@pytest.mark.integration
class TestAlarmConfirmAllAPI:
    """批量确认端点（POST /api/alarm/confirm_all）"""

    def test_confirm_all(self, client, alarm_db):
        alarm_db.query.update_result = 5

        resp = client.post("/api/alarm/confirm_all", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"confirmed_count": 5}
        assert "已确认 5 条告警" in body["message"]
        assert alarm_db.query.update_values == {"status": "CONFIRMED"}
        assert alarm_db.session.commit_count == 1

    def test_confirm_all_with_account_filter(self, client, alarm_db):
        alarm_db.query.update_result = 2

        resp = client.post("/api/alarm/confirm_all", json={"account_id": "DQ"})

        assert resp.status_code == 200
        # 两次 filter 调用：第一次携带 状态+日期 两个条件，第二次为账户过滤
        assert len(alarm_db.query.filters) == 2
        assert len(alarm_db.query.filters[0]) == 2
        assert len(alarm_db.query.filters[1]) == 1

    def test_confirm_all_db_error(self, client, alarm_db):
        alarm_db.session.query_obj = None

        resp = client.post("/api/alarm/confirm_all", json={})

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "批量确认告警失败" in resp.json()["message"]


@pytest.mark.integration
class TestAlarmSuppressionAPI:
    """告警压制端点（/api/alarm/suppression*）"""

    def test_suppression_status_without_service(self, client):
        """AppContext 未注册告警服务时返回业务码 500"""
        resp = client.get("/api/alarm/suppression")

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "告警服务未初始化" in resp.json()["message"]

    def test_suppression_status(self, client, alarm_service):
        status = {"DQ": {"1min": {"suppressed": True, "since": "2026-09-01T10:00:00"}}}
        alarm_service.get_suppression_status = MagicMock(return_value=status)

        resp = client.get("/api/alarm/suppression", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == status
        alarm_service.get_suppression_status.assert_called_once_with("DQ")

    def test_suppression_status_error(self, client, alarm_service):
        alarm_service.get_suppression_status = MagicMock(side_effect=RuntimeError("boom"))

        resp = client.get("/api/alarm/suppression")

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "获取压制状态失败" in resp.json()["message"]

    def test_clear_suppression_with_indicator(self, client, alarm_service):
        resp = client.post("/api/alarm/suppression/clear/DQ", params={"indicator": "5min"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "[DQ] 5min" in body["message"]
        alarm_service.clear_suppression.assert_called_once_with("DQ", "5min")

    def test_clear_suppression_all_indicators(self, client, alarm_service):
        resp = client.post("/api/alarm/suppression/clear/DQ")

        assert resp.status_code == 200
        assert "所有压制状态" in resp.json()["message"]
        alarm_service.clear_suppression.assert_called_once_with("DQ", None)

    def test_clear_all_suppression(self, client, alarm_service):
        resp = client.post("/api/alarm/suppression/clear_all")

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert "已清除所有压制状态" in resp.json()["message"]
        alarm_service.clear_all_suppression.assert_called_once_with()
