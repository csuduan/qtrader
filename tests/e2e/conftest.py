from playwright.sync_api import Page, BrowserContext, expect


@pytest.fixture(scope="function")
def authenticated_page(browser_context: BrowserContext) -> Page:
    page = browser_context.new_page()
    page.goto("http://localhost:5173")
    return page


@pytest.fixture(scope="function")
def page(browser_context: BrowserContext) -> Page:
    return browser_context.new_page()
