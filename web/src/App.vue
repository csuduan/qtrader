<template>
  <el-container class="app-container">
    <!-- 侧边栏 -->
    <el-aside width="150px" class="sidebar">
      <div class="logo">
         <img :src="getLogo()" alt="logo" width="40" />
        <h2>Q-Trader</h2>
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
        <el-menu-item index="/account">
          <el-icon><User /></el-icon>
          <span>账户</span>
        </el-menu-item>
        <el-menu-item index="/trading">
          <el-icon><Operation /></el-icon>
          <span>交易</span>
        </el-menu-item>
        <el-menu-item index="/strategy">
          <el-icon><TrendCharts /></el-icon>
          <span>策略</span>
        </el-menu-item>
        <el-menu-item index="/rotation">
          <el-icon><RefreshRight /></el-icon>
          <span>换仓</span>
        </el-menu-item>
        <el-menu-item index="/system">
          <el-icon><Setting /></el-icon>
          <span>系统</span>
        </el-menu-item>
        <el-menu-item index="/alarms">
          <el-icon><Warning /></el-icon>
          <span>告警</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主体内容 -->
    <el-container class="main-container">
      <!-- 顶部栏 -->
      <el-header v-if="!$route.meta.hideHeader" class="header">
        <div class="header-left">
          <!-- 多账号模式：账户选择器 -->
          <template v-if="store.isMultiAccountMode">
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
            <el-dropdown trigger="click" @command="(cmd: string) => handleAccountAction(cmd, store.currentAccount?.account_id)" @click.stop>
              <el-button circle size="small" class="header-action-btn">
                <el-icon><MoreFilled /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <!-- 已连接状态：显示连接网关、断开网关、暂停交易、恢复交易 -->
                  <template v-if="isAccountConnected(store.currentAccount)">
                    <el-dropdown-item
                      :command="{ action: 'connect_gateway' }"
                      v-if="!store.currentAccount?.gateway_connected"
                    >
                      <el-icon><Connection /></el-icon>
                      连接网关
                    </el-dropdown-item>
                    <el-dropdown-item
                      :command="{ action: 'disconnect_gateway' }"
                      v-if="store.currentAccount?.gateway_connected"
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
                  </template>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <!-- 网关状态 -->
            <el-tag :type="store.currentAccount?.gateway_connected ? 'success' : 'info'" size="small">
              {{ store.currentAccount?.gateway_connected ? '已连接' : '已断开' }}
            </el-tag>
            <!-- 交易状态 -->
            <el-tag :type="store.currentAccount?.trade_paused ? 'warning' : 'success'" size="small">
              {{ store.currentAccount?.trade_paused ? '暂停交易' : '可交易' }}
            </el-tag>
          </template>

          <!-- 单账号模式：账户信息 -->
          <template v-else-if="store.account">
            <span>账户: {{ store.account.account_id }}</span>
            <el-divider direction="vertical" />
            <span>可用: ¥{{ formatNumber(store.account.available) }}</span>
            <el-divider direction="vertical" />
            <span>浮动盈亏: <span :class="store.account.float_profit >= 0 ? 'profit' : 'loss'">¥{{ formatNumber(store.account.float_profit) }}</span></span>
          </template>
        </div>
        <div class="header-right">
          <span>总资产: ¥{{ formatNumber(store.isMultiAccountMode ? (store.currentAccount?.balance || 0) : (store.account?.balance || 0)) }}</span>
          <el-divider direction="vertical" />
          <span :class="(store.isMultiAccountMode ? (store.currentAccount?.float_profit || 0) : (store.account?.float_profit || 0)) >= 0 ? 'profit' : 'loss'">
            总盈亏: ¥{{ formatNumber(store.isMultiAccountMode ? (store.currentAccount?.float_profit || 0) : (store.account?.float_profit || 0)) }}
          </span>
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
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useStore } from '@/stores'
import { accountApi } from '@/api'
import wsManager from '@/ws'
import type { Account } from '@/types'
import { ElMessage } from 'element-plus'

const store = useStore()

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
  if (store.isMultiAccountMode) {
    return store.currentAccount?.account_id || '请选择账户'
  }
  return store.account?.account_id || ''
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
    }
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  }
}

onMounted(async () => {
  // 加载初始数据
  await store.loadAllData()

  // 初始化 WebSocket
  store.initWebSocket()
})

onUnmounted(() => {
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

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 状态标签之间的竖线间距减小 */
.header-left .el-divider--vertical {
  margin: 0;
}

/* Header 中的操作按钮样式 */
.header-action-btn {
  padding: 4px;
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

.main-content {
  background-color: #f0f2f5;
  height: calc(100vh - 60px);
  overflow: auto;
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
</style>
