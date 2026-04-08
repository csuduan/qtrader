import { test, expect } from '@playwright/test'
import { loginAsAdmin, loginAsTrader } from './utils/auth'
import {
  navigateToSystemAdmin,
  openAddUserDialog,
  fillUserForm,
  saveUser,
  cancelUserForm,
  editUser,
  deleteUser,
  verifyUserInList
} from './utils/user-management'
import { testUsers, newUserTemplate, editUserTemplate } from './fixtures/users'

test.describe('用户管理功能 - 管理员权限', () => {
  test.beforeEach(async ({ page }) => {
    // 管理员登录
    await loginAsAdmin(page)
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('管理员可以查看用户管理页面', async ({ page }) => {
    // 导航到系统管理页面
    await navigateToSystemAdmin(page)
    await expect(page).toHaveURL(/\/admin\/system/)

    // 验证用户管理卡片存在
    await expect(page.locator('.el-card:has-text("用户管理")')).toBeVisible()

    // 验证用户表格存在
    const userTable = page.locator('.el-card:has-text("用户管理") .el-table')
    await expect(userTable).toBeVisible()

    // 验证表格列标题
    const headers = ['用户名', '用户ID', '角色', '创建时间', '操作']
    for (const header of headers) {
      await expect(page.locator(`.el-card:has-text("用户管理") th:has-text("${header}")`)).toBeVisible()
    }
  })

  test('管理员可以新增用户', async ({ page }) => {
    const testUser = {
      ...newUserTemplate,
      username: `new_${Date.now()}`
    }

    await navigateToSystemAdmin(page)

    // 打开新增用户对话框
    await openAddUserDialog(page)
    await expect(page.locator('.el-dialog:has-text("新增用户")')).toBeVisible()

    // 填写表单
    await fillUserForm(page, testUser)

    // 保存并等待对话框关闭（表示保存成功）
    await saveUser(page)
    await expect(page.locator('.el-dialog:has-text("新增用户")')).not.toBeVisible({ timeout: 10000 })

    // 验证用户出现在列表中
    await page.waitForTimeout(500)
    await verifyUserInList(page, testUser.username, true)

    // 清理：删除测试用户
    await deleteUser(page, testUser.username)
    await expect(page.locator('.el-message--success:has-text("用户已删除")')).toBeVisible()
  })

  test('管理员可以编辑用户', async ({ page }) => {
    // 先创建测试用户（使用同一时间戳）
    const timestamp = Date.now().toString().slice(-8)
    const testUser = {
      ...newUserTemplate,
      username: `e${timestamp}`
    }

    await navigateToSystemAdmin(page)

    // 创建新用户
    await openAddUserDialog(page)
    await fillUserForm(page, testUser)
    await saveUser(page)
    await expect(page.locator('.el-message--success:has-text("用户已创建")')).toBeVisible()

    // 编辑用户
    await editUser(page, testUser.username)
    await expect(page.locator('.el-dialog:has-text("编辑用户")')).toBeVisible()

    // 修改角色（后端不支持修改用户名，user_id是主键）
    await fillUserForm(page, {
      role: 'admin'
    })
    await saveUser(page)

    // 验证成功提示
    await expect(page.locator('.el-message--success:has-text("用户已更新")')).toBeVisible()

    // 等待对话框关闭
    await expect(page.locator('.el-dialog:has-text("编辑用户")')).not.toBeVisible()

    // 验证用户仍然存在（用户名未变）
    await page.waitForTimeout(500)
    await verifyUserInList(page, testUser.username, true)

    // 清理：删除测试用户
    await deleteUser(page, testUser.username)
  })

  test('管理员可以删除用户', async ({ page }) => {
    // 先创建测试用户
    const testUser = {
      ...newUserTemplate,
      username: `delete_${Date.now()}`
    }

    await navigateToSystemAdmin(page)

    // 创建新用户
    await openAddUserDialog(page)
    await fillUserForm(page, testUser)
    await saveUser(page)
    await expect(page.locator('.el-message--success')).toBeVisible()

    // 删除用户
    await deleteUser(page, testUser.username)

    // 验证确认对话框已关闭，显示成功提示
    await expect(page.locator('.el-message--success:has-text("用户已删除")')).toBeVisible()

    // 验证用户从列表中消失
    await verifyUserInList(page, testUser.username, false)
  })

  test('表单验证 - 新增用户时用户名必填', async ({ page }) => {
    await navigateToSystemAdmin(page)

    // 打开新增用户对话框
    await openAddUserDialog(page)
    await expect(page.locator('.el-dialog:has-text("新增用户")')).toBeVisible()

    // 只填写密码，不填写用户名
    await fillUserForm(page, { password: 'testpass123' })
    await saveUser(page)

    // 验证表单验证错误
    await expect(page.locator('.el-form-item__error:has-text("请输入用户名")')).toBeVisible()

    // 验证对话框未关闭
    await expect(page.locator('.el-dialog:has-text("新增用户")')).toBeVisible()

    // 取消关闭对话框
    await cancelUserForm(page)
  })

  test('表单验证 - 新增用户时密码必填', async ({ page }) => {
    await navigateToSystemAdmin(page)

    // 打开新增用户对话框
    await openAddUserDialog(page)

    // 只填写用户名，不填写密码
    await fillUserForm(page, { username: 'testuser_no_pass' })
    await saveUser(page)

    // 验证表单验证错误
    await expect(page.locator('.el-form-item__error:has-text("请输入密码")')).toBeVisible()

    // 取消关闭对话框
    await cancelUserForm(page)
  })

  test('取消删除用户', async ({ page }) => {
    // 创建测试用户（用户名不超过20字符）
    const testUser = {
      ...newUserTemplate,
      username: `cd${Date.now().toString().slice(-8)}`
    }

    await navigateToSystemAdmin(page)

    // 创建新用户
    await openAddUserDialog(page)
    await fillUserForm(page, testUser)
    await saveUser(page)
    // 等待对话框关闭并验证用户出现在列表中
    await expect(page.locator('.el-dialog:has-text("新增用户")')).not.toBeVisible()
    await verifyUserInList(page, testUser.username, true)

    // 点击删除但取消
    await deleteUser(page, testUser.username, false)

    // 验证用户仍然在列表中
    await verifyUserInList(page, testUser.username, true)

    // 清理：删除测试用户
    await deleteUser(page, testUser.username)
  })

  test('编辑用户时可以不修改密码', async ({ page }) => {
    const testUser = {
      ...newUserTemplate,
      username: `enp${Date.now().toString().slice(-7)}`
    }

    await navigateToSystemAdmin(page)

    // 创建新用户
    await openAddUserDialog(page)
    await fillUserForm(page, testUser)
    await saveUser(page)
    // 等待对话框关闭并验证用户出现在列表中
    await expect(page.locator('.el-dialog:has-text("新增用户")')).not.toBeVisible()
    await verifyUserInList(page, testUser.username, true)

    // 编辑用户，不修改密码
    await editUser(page, testUser.username)
    await expect(page.locator('.el-dialog:has-text("编辑用户")')).toBeVisible()

    // 只修改角色
    await fillUserForm(page, { role: 'admin' })
    await saveUser(page)

    // 验证成功提示
    await expect(page.locator('.el-message--success:has-text("用户已更新")')).toBeVisible()

    // 清理
    await deleteUser(page, testUser.username)
  })
})

test.describe('用户管理权限控制', () => {
  test('trader角色看不到管理菜单', async ({ page }) => {
    await loginAsTrader(page)
    await page.waitForURL(/\/dashboard/)

    // 验证管理菜单不可见
    await expect(page.locator('.el-sub-menu:has-text("管理")')).not.toBeVisible()

    // 直接访问系统管理URL应该被重定向到dashboard
    await page.goto('/admin/system')
    await expect(page).toHaveURL(/\/dashboard/)
  })
})

test.describe('用户管理边界场景', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page)
  })

  test('用户名长度验证 - 最小长度', async ({ page }) => {
    await navigateToSystemAdmin(page)
    await openAddUserDialog(page)

    // 输入2个字符的用户名
    await fillUserForm(page, { username: 'ab', password: 'testpass123' })
    await saveUser(page)

    // 验证长度验证错误
    await expect(page.locator('.el-form-item__error:has-text("用户名长度")')).toBeVisible()
    await cancelUserForm(page)
  })

  test('密码长度验证 - 最小长度', async ({ page }) => {
    await navigateToSystemAdmin(page)
    await openAddUserDialog(page)

    // 输入5个字符的密码
    await fillUserForm(page, { username: 'testuser', password: '12345' })
    await saveUser(page)

    // 验证长度验证错误
    await expect(page.locator('.el-form-item__error:has-text("密码长度")')).toBeVisible()
    await cancelUserForm(page)
  })
})