import pytest
from playwright.sync_api import Page, BrowserContext


@pytest.mark.e2e
class TestUserFlow:
    def test_login_and_connect(self, page: Page):
        page.goto("http://localhost:5173")
        
        page.wait_for_load_state("networkidle")
        
        assert page.title()

    def test_view_account_info(self, page: Page):
        page.goto("http://localhost:5173")
        page.wait_for_load_state("networkidle")
        
        account_section = page.query_selector(".account-info")
        assert account_section is not None

    def test_view_positions(self, page: Page):
        page.goto("http://localhost:5173")
        
        page.wait_for_selector(".positions-container", timeout=5000)
        
        positions_table = page.query_selector("table.positions")
        assert positions_table is not None

    def test_create_order(self, page: Page):
        page.goto("http://localhost:5173")
        page.wait_for_load_state("networkidle")
        
        page.click("button[data-testid='new-order-btn']")
        page.fill("input[name='symbol']", "SHFE.rb2505")
        page.fill("input[name='volume']", "1")
        page.fill("input[name='price']", "3500")
        
        page.click("button[type='submit']")
        
        success_message = page.query_selector(".message.success")
        assert success_message is not None

    def test_view_trades(self, page: Page):
        page.goto("http://localhost:5173")
        page.wait_for_load_state("networkidle")
        
        trades_section = page.query_selector(".trades-container")
        assert trades_section is not None

    def test_manage_scheduled_tasks(self, page: Page):
        page.goto("http://localhost:5173")
        page.wait_for_load_state("networkidle")
        
        page.click("a[href='/tasks']")
        
        page.wait_for_selector(".tasks-container")
        
        task_list = page.query_selector("table.tasks")
        assert task_list is not None
