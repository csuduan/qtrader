"""E2E 测试 fixtures

基于 pytest-playwright 插件（提供 page/browser fixture，base_url 见 pytest.ini）。
前置条件：前端 dev server 已启动（cd web && npm run dev，端口 3000）。

两种运行模式：
- 冒烟模式（默认）：屏蔽 API/WebSocket 并注入模拟登录态，仅验证页面渲染，
  无需后端，也不会触碰真实交易系统。
- 真实模式：设置 E2E_USERNAME / E2E_PASSWORD 环境变量后执行真实登录，
  可验证账户、持仓等依赖后端数据的流程；写路径用例（真实报单/撤单）仅在
  本模式生效，且受交易时段守卫约束（非交易时段自动 skip）。

安全约束：真实模式下仅允许使用 DQ 账户（登录后自动切换，模拟盘），
绝不操作其他账户；写路径用例只在交易时段内执行。
"""

import os
import re

import pytest
from playwright.sync_api import Page, expect

from qtrader.utils.trading_session import is_symbol_trading_time

E2E_USERNAME = os.environ.get("E2E_USERNAME", "")
E2E_PASSWORD = os.environ.get("E2E_PASSWORD", "")

# 测试唯一允许使用的交易账户
E2E_ACCOUNT_ID = "DQ"

# 写路径用例使用的合约（主力合约会换月，可用环境变量覆盖）
E2E_SYMBOL = os.environ.get("E2E_SYMBOL", "SHFE.rb2701")


def require_trading_session(symbol: str = E2E_SYMBOL) -> None:
    """写路径用例的交易时段守卫：非交易时段 skip 而非 fail"""
    if not is_symbol_trading_time(symbol):
        pytest.skip(f"{symbol} 非交易时段，跳过真实交易用例")

# 仅匹配后端接口路径（host 后紧跟 /api/ 或 /ws），
# 不能用 **/api/** 通配——那会把 Vite 的源码模块 /src/api/*.ts 也拦掉，导致应用无法挂载
API_ROUTE = re.compile(r"^\w+://[^/]+/api/")
WS_ROUTE = re.compile(r"^wss?://[^/]+/ws")


def _block_backend(page: Page) -> None:
    """屏蔽对后端 API/WebSocket 的访问，使页面稳定渲染为空数据状态。

    若不屏蔽而后端恰好在线，模拟 token 会触发 401 并被踢回登录页。
    """
    page.route(API_ROUTE, lambda route: route.abort())
    page.route(WS_ROUTE, lambda route: route.abort())


@pytest.fixture()
def authed_page(page: Page) -> Page:
    """处于已登录状态的页面，停在总览页。

    真实模式下登录后立即将账户切换为 DQ，后续所有账户相关操作均限定在该账户。
    """
    page.goto("/login")
    if E2E_USERNAME and E2E_PASSWORD:
        page.get_by_test_id("username-input").fill(E2E_USERNAME)
        page.get_by_test_id("password-input").fill(E2E_PASSWORD)
        page.get_by_role("button", name="登 录").click()
        page.wait_for_url("**/dashboard")
        # 前端默认自动选中第一个连接的账户（不一定是 DQ），必须显式切换
        page.goto("/account")
        page.locator(".account-selector").click()
        page.locator(".el-dropdown-menu:visible").get_by_text(E2E_ACCOUNT_ID, exact=True).click()
        expect(page.locator(".account-selector .account-name")).to_have_text(E2E_ACCOUNT_ID)
        page.goto("/dashboard")
    else:
        _block_backend(page)
        page.evaluate("""() => {
                localStorage.setItem('isLoggedIn', 'true');
                localStorage.setItem('token', 'e2e-mock-token');
                localStorage.setItem('userRole', 'admin');
            }""")
        page.goto("/dashboard")
    return page
