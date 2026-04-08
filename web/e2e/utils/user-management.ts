import { Page, expect } from '@playwright/test'

/**
 * 导航到系统管理页面
 * @param page - Playwright page 对象
 */
export async function navigateToSystemAdmin(page: Page): Promise<void> {
  // 点击"管理"菜单
  await page.locator('.el-sub-menu:has-text("管理")').click()
  // 点击"系统"子菜单
  await page.locator('.el-menu-item:has-text("系统")').click()
}

/**
 * 打开新增用户对话框
 * @param page - Playwright page 对象
 */
export async function openAddUserDialog(page: Page): Promise<void> {
  await page.locator('.el-card:has-text("用户管理") button:has-text("新增用户")').click()
}

/**
 * 填写用户表单
 * @param page - Playwright page 对象
 * @param userData - 用户数据
 */
export async function fillUserForm(
  page: Page,
  userData: {
    username?: string
    password?: string
    role?: string
  }
): Promise<void> {
  const dialog = page.locator('.el-dialog')

  if (userData.username !== undefined) {
    const usernameInput = dialog.locator('input[placeholder="请输入用户名"]')
    // 编辑模式下用户名输入框可能被禁用，只在启用时修改
    const isDisabled = await usernameInput.evaluate(el => (el as HTMLInputElement).disabled).catch(() => true)
    if (!isDisabled) {
      await usernameInput.clear()
      await usernameInput.fill(userData.username)
    }
  }

  if (userData.password !== undefined) {
    await dialog.locator('input[type="password"]').fill(userData.password)
  }

  if (userData.role !== undefined) {
    await dialog.locator('.el-select').click()
    const roleMap: Record<string, string> = {
      'admin': '管理员',
      'trader': '交易员',
      'guest': '访客'
    }
    await page.locator(`.el-select-dropdown__item:has-text("${roleMap[userData.role]}")`).click()
  }
}

/**
 * 保存用户
 * @param page - Playwright page 对象
 */
export async function saveUser(page: Page): Promise<void> {
  await page.locator('.el-dialog button:has-text("确定")').click()
}

/**
 * 取消用户表单
 * @param page - Playwright page 对象
 */
export async function cancelUserForm(page: Page): Promise<void> {
  await page.locator('.el-dialog button:has-text("取消")').click()
}

/**
 * 编辑用户
 * @param page - Playwright page 对象
 * @param username - 要编辑的用户名
 */
export async function editUser(page: Page, username: string): Promise<void> {
  const userRow = page.locator(`.el-card:has-text("用户管理") .el-table__row:has-text("${username}")`)
  await userRow.locator('button:has-text("编辑")').click()
}

/**
 * 删除用户
 * @param page - Playwright page 对象
 * @param username - 要删除的用户名
 * @param confirm - 是否确认删除（默认true）
 */
export async function deleteUser(page: Page, username: string, confirm: boolean = true): Promise<void> {
  const userRow = page.locator(`.el-card:has-text("用户管理") .el-table__row:has-text("${username}")`)
  await userRow.locator('button:has-text("删除")').click()

  if (confirm) {
    await page.locator('.el-message-box button:has-text("确定")').click()
  } else {
    await page.locator('.el-message-box button:has-text("取消")').click()
  }
}

/**
 * 验证用户是否在列表中
 * @param page - Playwright page 对象
 * @param username - 用户名
 * @param shouldExist - 是否应该存在（默认true）
 */
export async function verifyUserInList(
  page: Page,
  username: string,
  shouldExist: boolean = true
): Promise<void> {
  // 只检查第一列（用户名列）
  const userRow = page.locator(`.el-card:has-text("用户管理") .el-table__row`).filter({ hasText: username })
  if (shouldExist) {
    await expect(userRow).toBeVisible()
  } else {
    await expect(userRow).toBeHidden()
  }
}
