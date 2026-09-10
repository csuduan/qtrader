"""E2E 用户流程测试

安全约束：
- 冒烟模式（默认）零写操作：报单流程仅验证到"确认弹窗 → 返回修改"。
- 真实模式允许触发真实交易（仅 DQ 模拟盘账户）：报单指令、撤单等写路径
  用例仅在本模式生效，且受交易时段守卫约束（非交易时段自动 skip）。
- 真实模式下仅允许使用 DQ 账户（conftest 登录后自动切换），绝不操作其他账户。

默认冒烟模式（无后端、屏蔽 API）验证页面渲染；
设置 E2E_USERNAME / E2E_PASSWORD 后，真实登录相关用例生效。
"""

import os
import re
import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import E2E_SYMBOL, require_trading_session

requires_credentials = pytest.mark.skipif(
    not (os.environ.get("E2E_USERNAME") and os.environ.get("E2E_PASSWORD")),
    reason="未设置 E2E_USERNAME / E2E_PASSWORD，跳过依赖后端数据的用例",
)


@pytest.mark.e2e
class TestUserFlow:
    def test_visit_root_redirects_to_login(self, page: Page):
        """未登录访问根路径应跳转登录页并渲染登录表单"""
        page.goto("/")
        expect(page).to_have_url(re.compile(r"/login$"))
        expect(page.get_by_test_id("username-input")).to_be_visible()
        expect(page.get_by_test_id("password-input")).to_be_visible()

    def test_login_wrong_credentials_shows_error(self, page: Page):
        """错误凭据登录应在页面上提示错误信息"""
        page.goto("/login")
        page.get_by_test_id("username-input").fill("e2e-user")
        page.get_by_test_id("password-input").fill("wrong-password")
        page.get_by_role("button", name=re.compile("登\\s*录")).click()
        expect(page.locator(".el-message--error").first).to_be_visible()

    @requires_credentials
    def test_login_success_redirects_to_dashboard(self, page: Page):
        """正确凭据登录应跳转到总览页"""
        page.goto("/login")
        page.get_by_test_id("username-input").fill(os.environ["E2E_USERNAME"])
        page.get_by_test_id("password-input").fill(os.environ["E2E_PASSWORD"])
        page.get_by_role("button", name=re.compile("登\\s*录")).click()
        expect(page).to_have_url(re.compile(r"/dashboard$"))
        expect(page.locator(".account-cards")).to_be_visible()

    def test_dashboard_renders(self, authed_page: Page):
        """登录后总览页应渲染侧边栏菜单与账户卡片区域"""
        expect(authed_page.locator(".nav-menu")).to_be_visible()
        # 空账户态下卡片容器高度为0（不可见），断言挂载即可
        expect(authed_page.get_by_test_id("account-cards")).to_be_attached()
        expect(authed_page.get_by_text("总资产").first).to_be_visible()

    def test_account_trading_and_trade_tabs(self, authed_page: Page):
        """账户页：交易页签渲染委托表与报单入口，成交页签渲染成交表"""
        authed_page.goto("/account")
        authed_page.get_by_role("tab", name="账户交易").click()
        expect(authed_page.get_by_test_id("orders-table")).to_be_visible()
        expect(authed_page.get_by_test_id("new-order-btn")).to_be_visible()

        authed_page.get_by_role("tab", name="成交记录").click()
        expect(authed_page.get_by_test_id("trades-table")).to_be_visible()

    def test_order_dialog_flow_without_submission(self, authed_page: Page):
        """报单流程：打开弹窗→填写→下一步→确认弹窗→返回修改，全程不提交真实委托"""
        authed_page.goto("/account")
        authed_page.get_by_role("tab", name="账户交易").click()
        authed_page.get_by_test_id("new-order-btn").click()

        order_dialog = authed_page.get_by_role("dialog").filter(has_text="下一步")
        expect(order_dialog).to_be_visible()
        order_dialog.get_by_placeholder("如: rb2605").fill("rb2605")
        order_dialog.locator(".el-input-number input").first.fill("1")
        order_dialog.get_by_role("button", name="下一步").click()

        confirm_dialog = authed_page.get_by_role("dialog").filter(has_text="返回修改")
        expect(confirm_dialog).to_be_visible()
        confirm_dialog.get_by_role("button", name="返回修改").click()
        expect(order_dialog).to_be_visible()

    def test_scheduled_tasks_list_renders(self, authed_page: Page):
        """账户设置页签应渲染定时任务列表（仅查看，不执行启停操作）"""
        authed_page.goto("/account")
        authed_page.get_by_role("tab", name="账户设置").click()
        expect(authed_page.get_by_test_id("jobs-table")).to_be_visible()

    @requires_credentials
    def test_positions_table_renders(self, authed_page: Page):
        """真实环境下账户详情页签应渲染持仓表"""
        authed_page.goto("/account")
        expect(authed_page.get_by_test_id("positions-table")).to_be_visible()

    @requires_credentials
    def test_order_cmd_full_flow_trading(self, authed_page: Page):
        """真实交易（DQ 模拟盘）：报单指令全流程

        新增指令（市价=对手价追价）→ 未完成列表 RUNNING → 撤单重报直至全部成交
        → 已完成列表 ALL_COMPLETED。非交易时段自动跳过。
        """
        require_trading_session()
        page = authed_page
        page.goto("/account")
        page.get_by_role("tab", name="报单指令").click()

        # 表格 symbol 列不带交易所前缀（SHFE.rb2701 → rb2701）
        bare_symbol = E2E_SYMBOL.split(".")[-1]

        # 新增报单指令：1 手开仓，价格 0（市价=对手价追价）
        page.get_by_test_id("create-order-cmd-btn").click()
        dialog = page.get_by_role("dialog").filter(has_text="新增报单指令")
        expect(dialog).to_be_visible()
        dialog.get_by_test_id("create-order-cmd-symbol").fill(E2E_SYMBOL)
        dialog.locator(".el-input-number input").first.fill("1")
        dialog.get_by_test_id("create-order-cmd-submit").click()

        # 未完成列表出现该指令（RUNNING）
        # 限定在可见的报单指令面板内：账户详情持仓表也含该合约行（display:none）
        unfinished = page.locator("#pane-order-cmd tr:visible", has_text=bare_symbol)
        expect(unfinished.first).to_be_visible(timeout=10_000)

        # 轮询已完成页签：切换页签自带刷新，直至指令以 ALL_COMPLETED 结束
        deadline = time.time() + 90
        finished_text = ""
        while time.time() < deadline:
            page.locator(".el-radio-button", has_text="已完成").click()
            rows = page.locator("#pane-order-cmd tr:visible", has_text=bare_symbol)
            if rows.count() > 0:
                finished_text = rows.first.inner_text()
                if "ALL_COMPLETED" in finished_text:
                    break
            page.wait_for_timeout(3_000)
        assert "ALL_COMPLETED" in finished_text, f"指令未在时限内全部成交: {finished_text}"
