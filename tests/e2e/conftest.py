import pytest
from playwright.sync_api import Page, BrowserContext, expect


@pytest.fixture(scope="function")
def authenticated_page(context: BrowserContext) -> Page:
    page = context.new_page()
    page.goto("http://localhost:3000")
    return page


@pytest.fixture(scope="function")
def page(context: BrowserContext) -> Page:
    return context.new_page()
