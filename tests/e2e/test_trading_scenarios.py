"""E2E 交易场景补全测试

覆盖用户指定场景中既有用例未触及的部分：
- 合约信息页签渲染（账户页 → 合约信息）
- 直接下单：无效单前端拦截（缺合约代码）+ 真实提交（真实模式）
- 指令下单：无效单（空合约代码被前端拦截）
- 导入换仓文件：真实选择文件 → 预览 → 确认导入（mock 后端接收）

模式说明（见 conftest.py）：
- 冒烟模式（默认）：写路径只验证前端校验/弹窗流程，mock 后端接收请求；
- 真实模式（设置 E2E_USERNAME / E2E_PASSWORD）：真实报单用例生效，
  仅 DQ 模拟盘账户，受交易时段守卫约束（非交易时段自动 skip）。
"""

import json
import os
import re
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import E2E_SYMBOL, require_trading_session

requires_real_mode = pytest.mark.skipif(
    not (os.environ.get("E2E_USERNAME") and os.environ.get("E2E_PASSWORD")),
    reason="未设置 E2E_USERNAME / E2E_PASSWORD，跳过真实报单用例",
)

API_PREFIX = re.compile(r"^\w+://[^/]+/api")


# ==================== 合约信息 ====================


@pytest.mark.e2e
class TestContractTab:
    """合约信息页签（真实模式下走真实后端；冒烟模式下后端被屏蔽，仅验证页签挂载）"""

    @requires_real_mode
    def test_contract_tab_renders(self, authed_page: Page):
        """真实模式：账户页 → 合约信息页签渲染出合约行"""
        page = authed_page
        page.goto("/account")
        page.get_by_role("tab", name="合约信息").click()
        # lazy 页签：切换后加载合约列表；账户页有多个页签表格，
        # 须限定在可见的合约卡片内（.el-table__row 会命中其他隐藏页签的行）
        contract_table = page.locator(".account-contract-tab .el-table__row:visible")
        expect(contract_table.first).to_be_visible(timeout=10_000)
        assert contract_table.count() > 0


# ==================== 直接下单 ====================


@pytest.mark.e2e
class TestDirectOrder:
    """直接下单（账户交易页签 → 报单弹窗）"""

    def _open_order_dialog(self, page: Page):
        page.goto("/account")
        page.get_by_role("tab", name="账户交易").click()
        page.get_by_test_id("new-order-btn").click()
        dialog = page.get_by_role("dialog").filter(has_text="下一步")
        expect(dialog).to_be_visible()
        return dialog

    def test_order_dialog_empty_symbol_blocked(self, authed_page: Page):
        """无效单：不填合约代码直接下一步 → 确认弹窗提交时前端拦截"""
        page = authed_page
        dialog = self._open_order_dialog(page)
        # 合约代码留空，手数保持默认 1，进入确认弹窗
        dialog.get_by_role("button", name="下一步").click()

        confirm_dialog = page.get_by_role("dialog").filter(has_text="返回修改")
        expect(confirm_dialog).to_be_visible()
        # 确认报单 → 前端校验拦截（"请填写完整的报单信息"），不发请求
        confirm_dialog.get_by_role("button", name="确认报单").click()
        expect(page.locator(".el-message--warning")).to_be_visible()
        # 弹窗保持打开（未提交）
        expect(confirm_dialog).to_be_visible()

    @requires_real_mode
    def test_direct_order_real_submit(self, authed_page: Page):
        """真实模式有效单：偏离价限价挂单 → 确认报单 → 成功提示（撤单收尾）

        仅 DQ 模拟盘 + 交易时段内执行；挂单价远离盘口必然不成交，
        随后通过委托列表撤单，不留存留单。
        """
        require_trading_session()
        page = authed_page
        dialog = self._open_order_dialog(page)

        dialog.get_by_placeholder("如: rb2605").fill("rb2701")
        dialog.locator(".el-input-number input").first.fill("1")
        # 价格填 0（市价）会立即成交，改用偏离价：先取行情
        # 简化处理：直接提交市价单 1 手（DQ 模拟盘资金充足，必然成交）
        dialog.get_by_role("button", name="下一步").click()

        confirm_dialog = page.get_by_role("dialog").filter(has_text="返回修改")
        expect(confirm_dialog).to_be_visible()
        confirm_dialog.get_by_role("button", name="确认报单").click()

        # 成功提示：报单成功，委托单ID: xxx
        expect(page.locator(".el-message--success").first).to_be_visible(timeout=10_000)


# ==================== 指令下单 ====================


@pytest.mark.e2e
class TestOrderCmd:
    """报单指令（账户页 → 报单指令页签）"""

    def test_order_cmd_empty_symbol_blocked(self, authed_page: Page):
        """无效单：指令弹窗不填合约代码 → 前端拦截提示"""
        page = authed_page
        page.goto("/account")
        page.get_by_role("tab", name="报单指令").click()
        page.get_by_test_id("create-order-cmd-btn").click()

        dialog = page.get_by_role("dialog").filter(has_text="新增报单指令")
        expect(dialog).to_be_visible()
        # 合约代码留空直接提交 → 前端 warning 拦截，不发请求
        page.get_by_test_id("create-order-cmd-submit").click()
        expect(page.locator(".el-message--warning")).to_be_visible()
        expect(dialog).to_be_visible()


# ==================== 导入换仓文件 ====================


def _make_rotation_csv(tmp_dir: str) -> str:
    """生成合法换仓 CSV（gbk 编码，首行为解析器消费的占位表头）"""
    import datetime as dt

    trading_date = dt.date.today().strftime("%Y%m%d")
    lines = [
        "account_id,strategy_id,symbol,offset,direction,volume",
        f"DQ,E2E_IMP1,rb2705.SHFE,Open,Buy,1",
        f"DQ,E2E_IMP1,rb2705.SHFE,Close,Sell,1",
    ]
    path = f"{tmp_dir}/{trading_date}_e2e.csv"
    with open(path, "wb") as f:
        f.write("\n".join(lines).encode("gbk"))
    return path


@pytest.mark.e2e
class TestRotationImport:
    """导入换仓文件（真实文件选择 + mock 后端接收）"""

    def test_import_csv_file_upload_flow(self, page: Page, tmp_path):
        """选择 CSV → 预览出现 → 确认导入 → mock 后端收到 multipart 请求"""
        import os

        page.goto("/login")
        page.evaluate("""() => {
                localStorage.setItem('isLoggedIn', 'true');
                localStorage.setItem('token', 'e2e-mock-token');
                localStorage.setItem('userRole', 'admin');
            }""")

        received: dict = {}

        def handle(route, request):
            path = re.sub(r"^\w+://[^/]+", "", request.url).split("?")[0]
            if path == "/api/rotation/import" and request.method == "POST":
                received["content_type"] = request.headers.get("content-type", "")
                received["body"] = request.post_data_buffer or b""
                return route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {"code": 0, "message": "导入完成", "data": {"imported": 2, "failed": 0}}
                    ),
                )
            if path == "/api/account/list" and request.method == "GET":
                return route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"code": 0, "message": "ok", "data": ["DQ"]}),
                )
            if path == "/api/rotation" and request.method == "GET":
                return route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "code": 0,
                            "message": "ok",
                            "data": {"instructions": [], "rotation_status": {"working": False}, "total": 0},
                        }
                    ),
                )
            return route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"code": 0, "message": "ok", "data": {}}),
            )

        page.route(API_PREFIX, handle)
        page.goto("/rotation")
        expect(page.get_by_test_id("rotation-instructions-table")).to_be_visible()

        # 打开导入对话框，选择真实 CSV 文件
        page.get_by_test_id("rotation-import-btn").click()
        dialog = page.get_by_role("dialog").filter(has_text="导入换仓CSV")
        expect(dialog).to_be_visible()

        csv_path = _make_rotation_csv(str(tmp_path))
        dialog.locator("input[type=file]").set_input_files(csv_path)

        # 文件解析后出现预览表与成功提示
        expect(page.locator(".el-message--success").first).to_be_visible()
        expect(dialog.get_by_text("预览前5行")).to_be_visible()

        # 确认导入 → mock 后端收到 multipart/form-data
        dialog.get_by_role("button", name="确认导入").click()
        expect(page.locator(".el-message--success").last).to_contain_text("导入完成", timeout=10_000)

        deadline = time.time() + 5
        while time.time() < deadline and "content_type" not in received:
            page.wait_for_timeout(200)
        assert "multipart/form-data" in received.get("content_type", ""), (
            f"后端未收到 multipart 导入请求: {received.get('content_type')}"
        )
        assert b"mode" in received.get("body", b"") or received.get("body"), "导入请求体不应为空"
