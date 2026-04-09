<template>
  <!-- 主应用布局 -->
  <el-container v-if="!$route.meta.standalone" class="app-container">
    <!-- 桌面端侧边栏 -->
    <el-aside v-if="!isMobile" width="150px" class="sidebar">
      <div class="logo">
         <img :src="getLogo()" alt="logo" width="40" />
      </div>
      <el-menu
        :default-active="$route.path"
        router
        class="nav-menu"
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataBoard /></el-icon>
          <span>总览</span>
        </el-menu-item>

        <!-- 一级菜单：账户 -->
        <el-menu-item index="/account">
          <el-icon><User /></el-icon>
          <span>账户</span>
        </el-menu-item>

        <!-- 一级菜单：换仓 -->
        <el-menu-item index="/rotation">
          <el-icon><RefreshRight /></el-icon>
          <span>换仓</span>
        </el-menu-item>

        <!-- 一级菜单：策略 -->
        <el-menu-item index="/strategy">
          <el-icon><TrendCharts /></el-icon>
          <span>策略</span>
        </el-menu-item>

        <!-- 一级菜单：监控 -->
        <el-menu-item index="/alarms">
          <el-icon><Odometer /></el-icon>
          <span>监控</span>
        </el-menu-item>

        <!-- 管理子菜单（仅admin可见）-->
        <el-sub-menu v-if="isAdmin" index="/admin">
          <template #title>
            <el-icon><Tools /></el-icon>
            <span>管理</span>
          </template>
          <el-menu-item index="/admin/log">
            <el-icon><DocumentCopy /></el-icon>
            <span>日志</span>
          </el-menu-item>
          <el-menu-item index="/admin/system">
            <el-icon><Monitor /></el-icon>
            <span>系统</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <!-- 用户信息与退出 -->
      <div class="sidebar-footer">
        <el-dropdown trigger="click" placement="top">
          <div class="user-info">
            <el-icon><User /></el-icon>
            <span class="username">{{ currentUser }}</span>
            <el-icon class="arrow-icon"><ArrowUp /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                <el-icon><User /></el-icon>
                {{ currentUser }}
              </el-dropdown-item>
              <el-dropdown-item divided @click="handleLogout">
                <el-icon><SwitchButton /></el-icon>
                退出
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-aside>

    <!-- 移动端抽屉侧边栏 -->
    <el-drawer
      v-model="drawerVisible"
      direction="ltr"
      size="200px"
      :with-header="false"
      class="mobile-sidebar-drawer"
    >
      <div class="logo">
         <img :src="getLogo()" alt="logo" width="40" />
      </div>
      <el-menu
        :default-active="$route.path"
        router
        class="nav-menu"
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        @select="drawerVisible = false"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataBoard /></el-icon>
          <span>总览</span>
        </el-menu-item>

        <el-menu-item index="/account">
          <el-icon><User /></el-icon>
          <span>账户</span>
        </el-menu-item>

        <el-menu-item index="/rotation">
          <el-icon><RefreshRight /></el-icon>
          <span>换仓</span>
        </el-menu-item>

        <el-menu-item index="/strategy">
          <el-icon><TrendCharts /></el-icon>
          <span>策略</span>
        </el-menu-item>

        <el-menu-item index="/alarms">
          <el-icon><Odometer /></el-icon>
          <span>监控</span>
        </el-menu-item>

        <el-sub-menu v-if="isAdmin" index="/admin">
          <template #title>
            <el-icon><Tools /></el-icon>
            <span>管理</span>
          </template>
          <el-menu-item index="/admin/log">
            <el-icon><DocumentCopy /></el-icon>
            <span>日志</span>
          </el-menu-item>
          <el-menu-item index="/admin/system">
            <el-icon><Monitor /></el-icon>
            <span>系统</span>
          </el-menu-item>
        </el-sub-menu>

        <!-- 移动端退出登录 -->
        <div class="mobile-sidebar-footer">
          <el-divider />
          <div class="mobile-user-info" @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
            <span>退出 ({{ currentUser }})</span>
          </div>
        </div>
      </el-menu>
    </el-drawer>

    <!-- 主体内容 -->
    <el-container class="main-container">
      <!-- 顶部栏：移动端始终显示，桌面端非简化页面显示 -->
      <el-header v-if="isMobile || showAccountInfo" class="header" :class="{ 'is-mobile': isMobile, 'simple-header': !showAccountInfo }">
        <div class="header-left">
          <!-- 移动端菜单按钮 -->
          <el-button v-if="isMobile" text class="menu-btn" @click="drawerVisible = true">
            <el-icon :size="20"><Fold /></el-icon>
          </el-button>

          <!-- 只在账户/换仓/策略页面显示账户选择器等内容 -->
          <template v-if="showAccountInfo && store.accounts.length > 0">
            <el-dropdown @command="handleSwitchAccount" trigger="click">
              <div class="account-selector">
                <span class="account-name">{{ currentAccountName }}</span>
                <span class="account-status-dot" :class="getCurrentStatusDotClass()"></span>
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </div>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="acc in sortedAccounts"
                    :key="acc.account_id"
                    :command="acc.account_id"
                    :class="{ 'is-selected': acc.account_id === store.selectedAccountId, 'is-disabled': acc.status !== 'connected' }"
                    :disabled="acc.status !== 'connected'"
                  >
                    <div class="account-dropdown-item">
                      <span class="account-name">{{ acc.account_id }}</span>
                      <!-- 状态圆点 -->
                      <span class="account-status-dot" :class="getStatusDotClass(acc)"></span>
                    </div>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <!-- 账户操作按钮 -->
            <el-dropdown trigger="click" @command="(cmd: any) => handleAccountAction(cmd, store.currentAccount?.account_id)" @click.stop>
              <el-button circle size="small" class="header-action-btn">
                <el-icon><MoreFilled /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <!-- 已停止状态：显示启动Trader -->
                  <template v-if="isAccountStopped(store.currentAccount)">
                    <el-dropdown-item
                      :command="{ action: 'start_trader' }"
                    >
                      <el-icon><VideoPlay /></el-icon>
                      启动
                    </el-dropdown-item>
                  </template>
                  <!-- 已连接状态 -->
                  <template v-else-if="isAccountConnected(store.currentAccount)">
                    <el-dropdown-item
                      :command="{ action: 'sync' }"
                    >
                      <el-icon><Refresh /></el-icon>
                      同步数据
                    </el-dropdown-item>
                    <el-dropdown-item divided
                      :command="{ action: 'connect_gateway' }"
                      v-if="!store.currentAccount?.md_connected || !store.currentAccount?.td_connected"
                    >
                      <el-icon><Connection /></el-icon>
                      连接网关
                    </el-dropdown-item>
                    <el-dropdown-item
                      :command="{ action: 'disconnect_gateway' }"
                      v-if="store.currentAccount?.md_connected && store.currentAccount?.td_connected"
                    >
                      <el-icon><SwitchButton /></el-icon>
                      断开网关
                    </el-dropdown-item>
                    <el-dropdown-item
                      :command="{ action: 'pause' }"
                      v-if="!store.currentAccount?.trade_paused"
                    >
                      <el-icon><CircleClose /></el-icon>
                      暂停交易
                    </el-dropdown-item>
                    <el-dropdown-item
                      :command="{ action: 'resume' }"
                      v-if="store.currentAccount?.trade_paused"
                    >
                      <el-icon><CircleCheck /></el-icon>
                      恢复交易
                    </el-dropdown-item>
                    <el-dropdown-item divided
                      :command="{ action: 'stop_trader' }"
                      type="danger"
                    >
                      <el-icon><VideoPause /></el-icon>
                      停止
                    </el-dropdown-item>
                  </template>
                  <!-- 启动中状态 -->
                  <template v-else-if="isAccountStarting(store.currentAccount)">
                    <el-dropdown-item disabled>
                      <el-icon><Loading /></el-icon>
                      正在启动...
                    </el-dropdown-item>
                    <el-dropdown-item divided
                      :command="{ action: 'stop_trader' }"
                      type="danger"
                    >
                      <el-icon><VideoPause /></el-icon>
                      停止
                    </el-dropdown-item>
                  </template>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <!-- 行情连接状态 -->
            <el-tag :type="store.currentAccount?.md_connected ? 'success' : 'warning'" size="small">
              行情
            </el-tag>
            <!-- 交易连接状态 -->
            <el-tag :type="store.currentAccount?.td_connected ? 'success' : 'warning'" size="small">
              交易
            </el-tag>
            <!-- 交易状态 -->
            <el-tag v-if="store.currentAccount?.trade_paused" type="warning" size="small">暂停交易</el-tag>

          </template>

        </div>
        <div class="header-right">
          <!-- 只在账户/换仓/策略页面显示资产信息 -->
          <template v-if="showAccountInfo">
            <span>总资产: ¥{{ formatNumber(store.currentAccount?.balance || 0) }}</span>
            <el-divider direction="vertical" />
            <span :class="(store.currentAccount?.today_profit || 0) >= 0 ? 'profit' : 'loss'">
              今日盈亏: ¥{{ formatNumber(store.currentAccount?.today_profit || 0) }}
            </span>
          </template>
        </div>
      </el-header>

      <!-- 主内容区 -->
      <el-main class="main-content">
        <div class="content-wrapper">
          <router-view />
        </div>
      </el-main>
    </el-container>
  </el-container>

  <!-- 登录页独立布局 -->
  <router-view v-else />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useStore } from '@/stores'
import { accountApi, authApi } from '@/api'
import wsManager from '@/ws'
import type { Account } from '@/types'
import { ElMessage } from 'element-plus'

const store = useStore()
const router = useRouter()
const route = useRoute()
const isMobile = ref(false)
const drawerVisible = ref(false)

// 当前登录用户（使用 ref 以便响应式更新）
const currentUser = ref(localStorage.getItem('username') || '用户')

// 当前用户角色
const userRole = computed(() => {
  return localStorage.getItem('userRole') || 'guest'
})

// 是否是管理员
const isAdmin = computed(() => {
  return userRole.value === 'admin'
})

// 是否可以交易（admin 或 trader）
const canTrade = computed(() => {
  return userRole.value === 'admin' || userRole.value === 'trader'
})

// 是否显示账户信息（只在账户/换仓/策略页面显示）
const showAccountInfo = computed(() => {
  return route.meta.showAccountInfo === true
})

// 保留参考
console.log('User can trade:', canTrade.value)

// 退出登录
async function handleLogout() {
  try {
    await authApi.logout()
  } catch (error) {
    // 忽略错误
  }
  localStorage.removeItem('isLoggedIn')
  localStorage.removeItem('username')
  localStorage.removeItem('userRole')
  localStorage.removeItem('token')
  localStorage.removeItem('rememberMe')
  ElMessage.success('已退出登录')
  router.push('/login')
}

function checkMobile() {
  isMobile.value = window.innerWidth < 768
}

function getLogo() {
    return new URL("/logo.png", import.meta.url).href;
  }
// 格式化数字
function formatNumber(num: number): string {
  return num.toFixed(2)
}

// 排序后的账户列表：已连接的在前
const sortedAccounts = computed(() => {
  return [...store.accounts].sort((a, b) => {
    const aConnected = a.status === 'connected'
    const bConnected = b.status === 'connected'
    if (aConnected === bConnected) return 0
    return aConnected ? -1 : 1
  })
})

// 当前账户名称
const currentAccountName = computed(() => {
  return store.currentAccount?.account_id || '请选择账户'
})

// 获取当前账户的状态圆点样式
function getCurrentStatusDotClass() {
  return getStatusDotClass(store.currentAccount)
}

// 获取账户的状态圆点样式
function getStatusDotClass(acc: Account | null | undefined) {
  if (!acc) return 'status-dot-gray'
  if (isAccountStopped(acc)) return 'status-dot-gray'
  if (isAccountStarting(acc)) return 'status-dot-yellow'
  return 'status-dot-green'
}

// 切换账户
function handleSwitchAccount(accountId: string) {
  // 检查账户是否已连接
  const account = store.accounts.find(acc => acc.account_id === accountId)
  if (!account || account.status !== 'connected') {
    return
  }
  store.switchAccount(accountId)
}

// 账户状态判断函数
function isAccountStopped(acc: Account | null | undefined): boolean {
  return !acc || acc.status === 'stopped' || !acc.status
}

function isAccountStarting(acc: Account | null | undefined): boolean {
  return acc?.status === 'connecting'
}

function isAccountConnected(acc: Account | null | undefined): boolean {
  return acc?.status === 'connected'
}

// 处理账户操作
async function handleAccountAction(cmd: any, accountId: string | undefined) {
  if (!accountId) return

  const targetAccountId = accountId

  try {
    switch (cmd.action) {
      case 'start_trader':
        await accountApi.startTrader(targetAccountId)
        ElMessage.success('Trader已启动')
        await store.loadAllAccounts()
        break
      case 'stop_trader':
        await accountApi.stopTrader(targetAccountId)
        ElMessage.success('Trader已停止')
        await store.loadAllAccounts()
        break
      case 'connect_gateway':
        await accountApi.connectGateway(targetAccountId)
        ElMessage.success('连接网关成功')
        await store.loadAllAccounts()
        break
      case 'disconnect_gateway':
        await accountApi.disconnectGateway(targetAccountId)
        ElMessage.success('已断开网关')
        await store.loadAllAccounts()
        break
      case 'pause':
        await accountApi.pauseTrading(targetAccountId)
        ElMessage.success('交易已暂停')
        await store.loadAllAccounts()
        break
      case 'resume':
        await accountApi.resumeTrading(targetAccountId)
        ElMessage.success('交易已恢复')
        await store.loadAllAccounts()
        break
      case 'sync':
        await accountApi.syncAccount(targetAccountId)
        ElMessage.success('同步成功')
        await store.loadAllAccounts()
        break
    }
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  }
}

onMounted(async () => {
  checkMobile()
  window.addEventListener('resize', checkMobile)

  // 更新当前用户名
  currentUser.value = localStorage.getItem('username') || '用户'

  // 只在已登录状态下加载数据
  const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true'
  if (isLoggedIn) {
    // 加载初始数据
    await store.loadAllData()

    // 初始化 WebSocket
    store.initWebSocket()
  }
})

// 监听路由变化，登录后加载数据并更新用户信息
watch(() => route.path, async (newPath, oldPath) => {
  // 从登录页跳转到其他页面时，加载数据
  if (oldPath === '/login' && newPath !== '/login') {
    // 更新当前用户名
    currentUser.value = localStorage.getItem('username') || '用户'

    const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true'
    if (isLoggedIn) {
      await store.loadAllData()
      store.initWebSocket()
    }
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
  wsManager.disconnect()
})
</script>

<style scoped>
#app {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}

.app-container {
  height: 100vh;
  width: 100vw;
  display: flex;
}

.sidebar {
  background-color: #304156;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
}

.logo {
  padding: 30px 20px;
  color: #fff;
  text-align: center;
  border-bottom: 1px solid #1f2d3d;
}

.logo h2 {
  margin: 0 0 10px 0;
  font-size: 20px;
  font-weight: 600;
}

.logo p {
  margin: 0;
  font-size: 12px;
  color: #8391a5;
}

.nav-menu {
  border-right: none;
  flex: 1;
  overflow-y: auto;
}

/* 侧边栏底部用户信息 */
.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid #1f2d3d;
  background-color: #304156;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #bfcbd9;
  font-size: 14px;
  cursor: pointer;
  padding: 8px;
  border-radius: 4px;
  transition: all 0.3s;
}

.user-info:hover {
  background-color: #263445;
  color: #409eff;
}

.username {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.arrow-icon {
  font-size: 12px;
}

/* 移动端侧边栏底部 */
.mobile-sidebar-footer {
  padding: 8px 16px;
  margin-top: auto;
}

.mobile-user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #bfcbd9;
  font-size: 14px;
  cursor: pointer;
  padding: 12px 8px;
  border-radius: 4px;
  transition: all 0.3s;
}

.mobile-user-info:hover {
  background-color: #263445;
  color: #f56c6c;
}

.main-container {
  flex: 1;
  min-width: 0;
}

.header {
  background-color: #fff;
  border-bottom: 1px solid #e6e6e6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
  overflow: visible;
}

.header.is-mobile {
  padding: 0 12px;
  flex-wrap: wrap;
  height: auto;
  min-height: 60px;
  gap: 8px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.header.is-mobile .header-left {
  gap: 6px;
}

.header.is-mobile .header-right {
  width: 100%;
  justify-content: flex-end;
  font-size: 13px;
  padding-bottom: 8px;
}

.menu-btn {
  padding: 6px;
  margin-right: 4px;
}

/* 状态标签之间的竖线间距减小 */
.header-left .el-divider--vertical {
  margin: 0;
}

/* Header 中的操作按钮样式 */
.header-action-btn {
  padding: 4px;
}

.user-btn {
  padding: 4px;
  margin-left: 4px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* header 右侧文字颜色 */
.header-right span {
  color: #606266;
}

.account-info {
  display: flex;
  align-items: center;
  font-size: 14px;
}

.ml-2 {
  margin-left: 8px;
}

.profit {
  color: #67c23a;
  font-weight: 600;
}

.loss {
  color: #f56c6c;
  font-weight: 600;
}

.main-container {
  display: flex;
  flex-direction: column;
}

.main-content {
  background-color: #f0f2f5;
  flex: 1;
  overflow: auto;
}

.header {
  flex-shrink: 0;
}

.content-wrapper {
  width: 100%;
}

/* 账户选择器样式 */
.account-selector {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background-color: #f5f7fa;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.3s;
  gap: 8px;
}

.account-selector:hover {
  background-color: #e6e8eb;
}

.account-selector .account-name {
  font-size: 14px;
  font-weight: 500;
}

/* Header 中的状态圆点 */
.header-left .account-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.account-dropdown-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
}

.account-dropdown-item .account-name {
  font-size: 14px;
  font-weight: 500;
}

/* 下拉项中的状态圆点 */
.account-dropdown-item .account-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

/* 状态圆点颜色 */
.status-dot-gray {
  background-color: #909399;
}

.status-dot-yellow {
  background-color: #e6a23c;
}

.status-dot-green {
  background-color: #67c23a;
}

/* 禁用状态的账户选项 */
.el-dropdown-menu__item.is-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.el-dropdown-menu__item.is-disabled:hover {
  background-color: transparent !important;
  cursor: not-allowed;
}

.summary-info {
  display: flex;
  align-items: center;
  font-size: 14px;
}

.summary-info span {
  white-space: nowrap;
}

/* 用户名样式 */
.user-name-wrapper {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background-color 0.3s;
}

.user-name-wrapper:hover {
  background-color: #f5f7fa;
}

.username-text {
  font-size: 14px;
  color: #606266;
}

.arrow-down {
  font-size: 12px;
  color: #909399;
}

/* 简化header样式 */
.simple-header .header-left {
  flex: 1;
}

@media (max-width: 767px) {
  .simple-header {
    justify-content: space-between;
  }
}
</style>

<!-- 全局样式：用于下拉菜单等 Portal 渲染的组件 -->
<style>
/* 选中状态的菜单项 */
.el-dropdown-menu__item.is-selected {
  background-color: #ecf5ff !important;
  color: #409eff !important;
  font-weight: 600;
}

/* 选中状态下的圆点更亮 */
.el-dropdown-menu__item.is-selected .account-status-dot.status-dot-green {
  background-color: #5daf34;
  box-shadow: 0 0 4px rgba(103, 194, 58, 0.5);
}

/* 移动端抽屉样式覆盖 */
.mobile-sidebar-drawer .el-drawer__body {
  padding: 0;
  background-color: #304156;
}
</style>
