import { Page } from '@playwright/test'
import { testUsers } from '../fixtures/users'

/**
 * 用户登录
 * @param page - Playwright page 对象
 * @param username - 用户名
 * @param password - 密码
 */
export async function login(page: Page, username: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.locator('input[placeholder="用户名"]').fill(username)
  await page.locator('input[placeholder="密码"]').fill(password)
  await page.locator('.login-btn').click()
  // 等待登录完成并跳转到 dashboard
  await page.waitForURL(/\/dashboard/)
  // 等待页面加载完成
  await page.waitForLoadState('networkidle')
}

/**
 * 管理员登录
 * @param page - Playwright page 对象
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  await login(page, testUsers.admin.username, testUsers.admin.password)
}

/**
 * 交易员登录
 * @param page - Playwright page 对象
 */
export async function loginAsTrader(page: Page): Promise<void> {
  await login(page, testUsers.trader.username, testUsers.trader.password)
}

/**
 * 登出
 * @param page - Playwright page 对象
 */
export async function logout(page: Page): Promise<void> {
  // 点击用户下拉菜单
  await page.locator('.sidebar-footer .user-info').click()
  // 点击退出
  await page.locator('.el-dropdown-menu__item:has-text("退出")').click()
}
