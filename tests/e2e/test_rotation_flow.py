"""E2E 换仓流程测试（mock 后端，无真实交易）

换仓是本系统最核心的功能，本文件用 Playwright route mock 覆盖完整用户流程：

1. 指令列表渲染（多状态：待执行/进行中/已完成/失败）
2. 编辑指令（改手数/方向 → 保存）
3. 启停开关（enabled 切换触发 PUT）
4. 开始换仓 → 确认弹窗 → 轮询进度 → filled_volume 实时更新 → COMPLETED
   （对应"未找到OrderCmd"回归：进度必须能从执行中更新到终态，不得停留在中间值）
5. 停止换仓 → 确认弹窗
6. 批量删除 → 确认弹窗 → 列表移除
7. 导入CSV对话框流程（选择模式，不上传真实文件）
8. 仓位比对页签渲染与目标手数编辑

安全约束：所有 API 均被 route mock 拦截，绝不触达真实后端；
真实模式下同样使用 mock（换仓写操作不允许在 E2E 中真实执行）。
"""

import json
import re
import time
from typing import Any

import pytest
from playwright.sync_api import Page, expect

# ==================== mock 数据与路由 ====================

API_PREFIX = re.compile(r"^\w+://[^/]+/api")


def _wait_for_request(page: Page, backend: "RotationBackend", req: tuple[str, str], timeout: float = 5.0):
    """轮询等待 mock 后端收到指定请求（expect() 不支持普通 Python 断言）"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if req in backend.requests:
            return
        page.wait_for_timeout(200)
    assert req in backend.requests, f"后端未收到请求 {req}，实际: {backend.requests[-10:]}"


def _instruction(
    id: int,
    *,
    symbol: str = "SHFE.rb2505",
    strategy_id: str = "rsi_001",
    direction: str = "BUY",
    offset: str = "OPEN",
    volume: int = 10,
    filled_volume: int = 0,
    remaining_volume: int | None = None,
    status: str = "PENDING",
    enabled: bool = True,
    error_message: str | None = None,
) -> dict[str, Any]:
    """构造一条换仓指令（字段与后端 RotationInstruction 对齐）"""
    return {
        "id": id,
        "account_id": "DQ",
        "strategy_id": strategy_id,
        "symbol": symbol,
        "exchange_id": symbol.split(".")[-1] if "." in symbol else symbol,
        "direction": direction,
        "offset": offset,
        "volume": volume,
        "filled_volume": filled_volume,
        "pending_volume": volume - filled_volume if status == "RUNNING" else 0,
        "remaining_volume": (
            volume - filled_volume if remaining_volume is None else remaining_volume
        ),
        "price": 3500.0,
        "order_time": "09:00:00",
        "trading_date": "20260904",
        "enabled": enabled,
        "status": status,
        "attempt_count": 0,
        "remaining_attempts": 3,
        "current_order_id": "cmd_abc123" if status == "RUNNING" else None,
        "last_attempt_time": None,
        "error_message": error_message,
        "source": "csv",
        "is_deleted": False,
        "created_at": "2026-09-04T09:00:00",
        "updated_at": "2026-09-04T09:00:00",
    }


def _list_payload(instructions: list[dict], working: bool = False) -> dict:
    return {
        "instructions": instructions,
        "rotation_status": {"working": working, "is_manual": False},
        "total": len(instructions),
        "limit": 100,
        "offset": 0,
    }


class RotationBackend:
    """用内存状态模拟换仓后端的 route handler

    - GET  /api/rotation            → 指令列表（含 rotation_status）
    - PUT  /api/rotation/{id}       → 编辑指令
    - POST /api/rotation/start      → 开始换仓（切换 working，驱动进度推进）
    - POST /api/rotation/stop       → 停止换仓
    - POST /api/rotation/batch/delete → 批量删除
    """

    def __init__(self, instructions: list[dict]):
        self.instructions = {inst["id"]: inst for inst in instructions}
        self.working = False
        self.requests: list[tuple[str, str]] = []  # (method, path) 审计
        # 进度推进剧本：每次轮询 GET 列表时步进一次（filled_volume 沿此序列推进）
        self.progress_script: dict[int, list[int]] = {}

    # ---- 路由安装 ----
    def install(self, page: Page) -> None:
        page.route(API_PREFIX, self._handle)

    def _handle(self, route, request):
        method, url = request.method, request.url
        path = re.sub(r"^\w+://[^/]+", "", url).split("?")[0]
        self.requests.append((method, path))

        if path == "/api/rotation" and method == "GET":
            self._advance_progress()
            payload = _list_payload(list(self.instructions.values()), self.working)
            return self._json(route, {"code": 0, "message": "ok", "data": payload})

        # 账户列表：store 依赖它设置 selectedAccountId（各写操作的前置条件）
        if path == "/api/account/list" and method == "GET":
            return self._json(route, {"code": 0, "message": "ok", "data": ["DQ"]})

        m = re.match(r"^/api/rotation/(\d+)$", path)
        if m and method == "PUT":
            inst = self.instructions.get(int(m.group(1)))
            if inst:
                body = json.loads(request.post_data or "{}")
                for key in ("direction", "offset", "volume", "enabled"):
                    if key in body:
                        inst[key] = body[key]
                return self._json(route, {"code": 0, "message": "ok", "data": inst})
            return self._json(route, {"code": 1, "message": "not found", "data": None})

        if path == "/api/rotation/start" and method == "POST":
            self.working = True
            for inst in self.instructions.values():
                if inst["status"] == "PENDING" and inst["enabled"]:
                    inst["status"] = "RUNNING"
                    inst["current_order_id"] = f"cmd_{inst['id']}"
            return self._json(route, {"code": 0, "message": "换仓流程已启动", "data": None})

        if path == "/api/rotation/stop" and method == "POST":
            self.working = False
            for inst in self.instructions.values():
                if inst["status"] == "RUNNING":
                    inst["status"] = "FAILED"
                    inst["error_message"] = "手动停止"
                    inst["current_order_id"] = None
            return self._json(route, {"code": 0, "message": "已停止", "data": None})

        if path == "/api/rotation/batch/delete" and method == "POST":
            body = json.loads(request.post_data or "{}")
            for iid in body.get("ids", []):
                self.instructions.pop(int(iid), None)
            return self._json(route, {"code": 0, "message": "ok", "data": {"deleted": len(body.get("ids", []))}})

        # 其余账户/系统类接口返回空态，保证页面可渲染
        return self._json(route, {"code": 0, "message": "ok", "data": {}})

    @staticmethod
    def _json(route, payload):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    # ---- 进度剧本 ----
    def set_progress_script(self, inst_id: int, filled_seq: list[int]) -> None:
        """设定指令的成交推进序列，如 [3, 7, 10]，每次列表轮询取下一个值"""
        self.progress_script[inst_id] = list(filled_seq)

    def _advance_progress(self):
        """轮询钩子：按剧本推进 filled_volume，走完后置 COMPLETED 并结束 working

        仅在换仓进行中（working=True）推进，避免页面加载期的轮询提前消费剧本。
        """
        if not self.working:
            return
        for inst_id, seq in self.progress_script.items():
            inst = self.instructions.get(inst_id)
            if not inst or not seq:
                continue
            filled = seq.pop(0)
            inst["filled_volume"] = filled
            inst["remaining_volume"] = inst["volume"] - filled
            inst["pending_volume"] = inst["volume"] - filled
            if not seq:  # 剧本演完 → 终态
                inst["status"] = "COMPLETED"
                inst["pending_volume"] = 0
                inst["current_order_id"] = None
        # 所有指令都到终态后结束 working（停止轮询）
        if self.progress_script and all(
            not seq for seq in self.progress_script.values()
        ) and all(
            self.instructions[i].get("status") in ("COMPLETED", "FAILED")
            for i in self.progress_script
            if i in self.instructions
        ):
            self.working = False


def _authed(page: Page) -> Page:
    """注入模拟登录态（冒烟模式同款）"""
    page.evaluate("""() => {
        localStorage.setItem('isLoggedIn', 'true');
        localStorage.setItem('token', 'e2e-mock-token');
        localStorage.setItem('userRole', 'admin');
    }""")
    return page


@pytest.fixture()
def rotation_page(page: Page) -> Page:
    """已登录、打开换仓页、后端已 mock 的页面"""
    # 先导航到应用域（about:blank 上无法访问 localStorage）
    page.goto("/login")
    _authed(page)
    backend = RotationBackend([
        _instruction(1, volume=10, status="PENDING"),
        _instruction(2, symbol="SHFE.hc2505", strategy_id="rsi_002", direction="SELL",
                     offset="CLOSE", volume=5, status="RUNNING", filled_volume=2),
        _instruction(3, symbol="SHFE.ru2505", volume=8, status="COMPLETED", filled_volume=8),
        _instruction(4, symbol="SHFE.cu2505", volume=4, status="FAILED", error_message="报单被拒"),
        _instruction(5, symbol="SHFE.ag2506", volume=6, enabled=False, status="PENDING"),
    ])
    backend.install(page)
    page.goto("/rotation")
    expect(page.get_by_test_id("rotation-instructions-table")).to_be_visible()
    page._rotation_backend = backend  # 挂到 page 上供用例断言
    return page


# ==================== 用例 ====================


@pytest.mark.e2e
class TestRotationListRender:
    """换仓页与指令列表渲染"""

    def test_table_renders_all_status_rows(self, rotation_page: Page):
        """多状态指令（待执行/进行中/已完成/失败/停用）应全部渲染"""
        table = rotation_page.get_by_test_id("rotation-instructions-table")
        expect(table).to_contain_text("SHFE.rb2505")
        expect(table).to_contain_text("SHFE.hc2505")
        # 进行中行显示剩余手数提示
        expect(table.get_by_test_id("rotation-progress-2")).to_contain_text("2/5")
        # 已完成状态标签
        expect(table.get_by_test_id("rotation-status-3")).to_have_text("已完成")
        # 失败行显示错误信息
        expect(table.get_by_test_id("rotation-status-4")).to_contain_text("报单被拒")
        # 待执行
        expect(table.get_by_test_id("rotation-status-1")).to_have_text("待执行")

    def test_disabled_row_styled(self, rotation_page: Page):
        """停用指令行应有 disabled-row 样式类"""
        expect(
            rotation_page.get_by_test_id("rotation-instructions-table").locator(
                "tr.disabled-row"
            )
        ).to_have_count(1)

    def test_compare_tab_renders(self, rotation_page: Page):
        """仓位比对页签可切换并渲染比对表"""
        rotation_page.get_by_role("tab", name="仓位比对").click()
        expect(rotation_page.get_by_test_id("position-compare-table")).to_be_visible()


@pytest.mark.e2e
class TestRotationEdit:
    """编辑指令流程"""

    def test_edit_volume_and_save(self, rotation_page: Page):
        """编辑手数 → 保存 → PUT 请求携带新值且行刷新"""
        row = rotation_page.get_by_test_id("rotation-instructions-table").locator("tr").filter(
            has_text="SHFE.rb2505"
        ).first
        row.get_by_test_id("rotation-edit-btn-1").click()

        dialog = rotation_page.get_by_role("dialog").filter(has_text="编辑换仓指令")
        expect(dialog).to_be_visible()
        dialog.locator(".el-input-number input").fill("20")
        dialog.get_by_test_id("rotation-edit-save-btn").click()

        expect(dialog).not_to_be_visible()
        # 后端收到编辑请求
        backend = rotation_page._rotation_backend
        assert ("PUT", "/api/rotation/1") in backend.requests
        assert backend.instructions[1]["volume"] == 20
        # 列表刷新显示新手数
        expect(row).to_contain_text("20")

    def test_enable_toggle_sends_update(self, rotation_page: Page):
        """启停开关切换应触发 PUT 更新 enabled"""
        rotation_page.get_by_test_id("rotation-instructions-table").locator(
            ".el-switch"
        ).first.click()
        backend = rotation_page._rotation_backend
        _wait_for_request(rotation_page, backend, ("PUT", "/api/rotation/1"))
        assert backend.instructions[1]["enabled"] is False


@pytest.mark.e2e
class TestRotationExecution:
    """换仓执行核心流程（进度轮询与终态回写）"""

    def test_start_rotation_progress_updates_to_completed(self, rotation_page: Page):
        """开始换仓 → 进度沿剧本推进 → filled_volume 实时更新 → 终态已完成

        对应"未找到OrderCmd: xxx"回归：若指令执行中被移出可查状态，
        前端进度将停留中间值，本用例的终态断言会失败。
        """
        backend = rotation_page._rotation_backend
        # 剧本：10手分三批成交 3 → 7 → 10
        backend.set_progress_script(1, [3, 7, 10])

        rotation_page.get_by_test_id("start-rotation-btn").click()
        confirm = rotation_page.get_by_role("dialog").filter(has_text="确认换仓")
        # Element Plus 未配置中文 locale，MessageBox 确认按钮为 "OK"
        confirm.get_by_role("button", name="OK").click()

        # 换仓启动后按钮切换为"停止换仓"
        expect(rotation_page.get_by_test_id("stop-rotation-btn")).to_be_visible()

        # 进度必须从中间值推进到终态（轮询周期2s，剧本3步，放宽到30s）
        progress = rotation_page.get_by_test_id("rotation-progress-1")
        expect(progress).to_contain_text("10/10", timeout=30_000)
        expect(rotation_page.get_by_test_id("rotation-status-1")).to_have_text(
            "已完成", timeout=10_000
        )
        # 全部完成后按钮回到"开始换仓"，轮询停止
        expect(rotation_page.get_by_test_id("start-rotation-btn")).to_be_visible()

    def test_stop_rotation_cancels_running(self, rotation_page: Page):
        """进行中的换仓可通过停止按钮撤单终止，指令标记失败"""
        # 制造 working 状态（指令2已 RUNNING）
        backend = rotation_page._rotation_backend
        backend.working = True
        rotation_page.get_by_role("button", name="刷新").click()
        expect(rotation_page.get_by_test_id("stop-rotation-btn")).to_be_visible()

        rotation_page.get_by_test_id("stop-rotation-btn").click()
        confirm = rotation_page.get_by_role("dialog").filter(has_text="确认停止换仓")
        confirm.get_by_role("button", name="OK").click()

        expect(rotation_page.get_by_test_id("start-rotation-btn")).to_be_visible()
        expect(rotation_page.get_by_test_id("rotation-status-2")).to_contain_text(
            "手动停止", timeout=10_000
        )
        assert ("POST", "/api/rotation/stop") in backend.requests

    def test_batch_delete_selected(self, rotation_page: Page):
        """勾选多条指令 → 批量删除 → 确认 → 列表移除"""
        table = rotation_page.get_by_test_id("rotation-instructions-table")
        # 勾选第1、2行
        rows = table.locator("tbody tr")
        rows.nth(0).locator(".el-checkbox").click()
        rows.nth(1).locator(".el-checkbox").click()

        rotation_page.get_by_role("button", name=re.compile("删除选中")).click()
        confirm = rotation_page.get_by_role("dialog").filter(has_text="确认删除")
        confirm.get_by_role("button", name="OK").click()

        backend = rotation_page._rotation_backend
        assert ("POST", "/api/rotation/batch/delete") in backend.requests
        assert 1 not in backend.instructions
        assert 2 not in backend.instructions
        expect(table).not_to_contain_text("SHFE.rb2505")

    def test_import_dialog_flow(self, rotation_page: Page):
        """导入CSV对话框：打开 → 模式选择 → 取消（不实际上传）"""
        rotation_page.get_by_test_id("rotation-import-btn").click()
        dialog = rotation_page.get_by_role("dialog").filter(has_text="导入换仓CSV")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_text("CSV格式参考实例")).to_be_visible()
        dialog.get_by_role("button", name="取消").click()
        expect(dialog).not_to_be_visible()

    def test_start_rotation_cancel_keeps_idle(self, rotation_page: Page):
        """开始换仓确认弹窗点取消 → 不发请求、按钮状态不变"""
        rotation_page.get_by_test_id("start-rotation-btn").click()
        confirm = rotation_page.get_by_role("dialog").filter(has_text="确认换仓")
        confirm.get_by_role("button", name="Cancel").click()

        expect(confirm).not_to_be_visible()
        backend = rotation_page._rotation_backend
        assert ("POST", "/api/rotation/start") not in backend.requests
        expect(rotation_page.get_by_test_id("start-rotation-btn")).to_be_visible()
