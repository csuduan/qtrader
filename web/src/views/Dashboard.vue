<template>
  <div class="dashboard">
    <!-- 账户卡片列表 -->
    <div class="account-cards" data-testid="account-cards">
      <el-row :gutter="20">
        <el-col :xs="12" :sm="12" :lg="6" v-for="acc in sortedAccounts" :key="acc.account_id">
          <el-card
            shadow="hover"
            :class="getAccountCardClass(acc)"
            class="account-card"
            @click="handleCardClick(acc)"
          >
            <div class="account-card-header">
              <div class="account-title-row">
                <div class="account-name-wrapper">
                  <span class="account-id">{{ acc.account_id }}</span>
                  <span class="account-status-dot" :class="getStatusDotClass(acc)"></span>
                  <!-- 状态标签放在圆点后面 -->
                  <div class="account-status-tags-inline">
                    <!-- 未连接状态：只显示主标签 -->
                    <el-tag v-if="!isAccountConnected(acc)" :type="getStatusTagType(acc)" size="small" disable-transitions>
                      {{ getStatusText(acc) }}
                    </el-tag>
                    <!-- 已连接状态：显示行情/交易连接状态 -->
                    <template v-if="isAccountConnected(acc)">
                      <el-tag :type="acc.md_connected ? 'success' : 'warning'" size="small" disable-transitions>
                        行情
                      </el-tag>
                      <el-tag :type="acc.td_connected ? 'success' : 'warning'" size="small" disable-transitions>
                        交易
                      </el-tag>
                      <el-tag v-if="acc.trade_paused" type="warning" size="small" disable-transitions>暂停交易</el-tag>
                    </template>
                  </div>
                </div>
                <el-dropdown trigger="click" @command="(cmd: string) => handleAccountAction(cmd, acc.account_id)" @click.stop>
                  <el-button circle size="small" class="action-btn" :disabled="!canOperate(acc)">
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <!-- 未连接状态：显示启动Trader -->
                      <template v-if="!isAccountConnected(acc)">
                        <el-dropdown-item
                          :command="{ action: 'start_trader', accountId: acc.account_id }"
                          v-if="isAccountStopped(acc)"
                        >
                          <el-icon><VideoPlay /></el-icon>
                          启动
                        </el-dropdown-item>
                      </template>
                      <!-- 已连接状态：显示连接网关、断开网关、暂停交易、恢复交易、重启、停止 -->
                      <template v-if="isAccountConnected(acc)">
                        <el-dropdown-item
                          :command="{ action: 'connect_gateway', accountId: acc.account_id }"
                          v-if="!acc.md_connected || !acc.td_connected"
                        >
                          <el-icon><Connection /></el-icon>
                          连接网关
                        </el-dropdown-item>
                        <el-dropdown-item
                          :command="{ action: 'disconnect_gateway', accountId: acc.account_id }"
                          v-if="acc.md_connected && acc.td_connected"
                        >
                          <el-icon><SwitchButton /></el-icon>
                          断开网关
                        </el-dropdown-item>
                        <el-dropdown-item
                          :command="{ action: 'pause', accountId: acc.account_id }"
                          v-if="!acc.trade_paused"
                        >
                          <el-icon><CircleClose /></el-icon>
                          暂停交易
                        </el-dropdown-item>
                        <el-dropdown-item
                          :command="{ action: 'resume', accountId: acc.account_id }"
                          v-if="acc.trade_paused"
                        >
                          <el-icon><CircleCheck /></el-icon>
                          恢复交易
                        </el-dropdown-item>
                        <el-dropdown-item :command="{ action: 'stop_trader', accountId: acc.account_id }">
                          <el-icon><VideoPause /></el-icon>
                          停止
                        </el-dropdown-item>
                      </template>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </div>

            <div class="account-card-stats">
              <div class="account-stat">
                <div class="account-stat-label">总资产</div>
                <div class="account-stat-value">¥{{ formatNumber(acc.balance) }}</div>
              </div>
              <div class="account-stat">
                <div class="account-stat-label">可用</div>
                <div class="account-stat-value">¥{{ formatNumber(acc.available) }}</div>
              </div>
              <div class="account-stat">
                <div class="account-stat-label">今日盈亏</div>
                <div class="account-stat-value" :class="(acc.today_profit || 0) >= 0 ? 'profit' : 'loss'">
                  ¥{{ formatNumber(acc.today_profit || 0) }}
                </div>
              </div>
              <div class="account-stat">
                <div class="account-stat-label">换仓进度</div>
                <div class="account-stat-value" :class="isRotationCompleted(acc) ? 'profit' : ''">
                  {{ getRotationProgressText(acc) }}
                </div>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 分割线 -->
    <el-divider />

    <el-row :gutter="20" class="mt-4">
      <!-- 告警统计 -->
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>告警统计</span>
              <el-link type="primary" @click="$router.push('/alarms')">查看全部</el-link>
            </div>
          </template>
          <el-row :gutter="10">
            <el-col :xs="8" :sm="8">
              <div class="stat-item">
                <div class="stat-label">今日总告警</div>
                <div class="stat-value" :class="alarmStats.today_total > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.today_total }}
                </div>
              </div>
            </el-col>
            <el-col :xs="8" :sm="8">
              <div class="stat-item">
                <div class="stat-label">最近1小时告警</div>
                <div class="stat-value" :class="alarmStats.last_hour > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.last_hour }}
                </div>
              </div>
            </el-col>
            <el-col :xs="8" :sm="8">
              <div class="stat-item">
                <div class="stat-label">最近5分钟告警</div>
                <div class="stat-value" :class="alarmStats.last_five_minutes > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.last_five_minutes }}
                </div>
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { alarmApi, systemApi, accountApi, rotationApi } from '@/api'
import type { Account } from '@/types'

const store = useStore()
const router = useRouter()
const alarmStats = ref({ today_total: 0, last_hour: 0, last_five_minutes: 0 })

// 各账户换仓进度: account_id -> { completed: 已完成条数, total: 总条数 }
const rotationProgress = ref<Record<string, { completed: number; total: number }>>({})
let rotationTimer: number | null = null

// 账户列表：按API返回的原始顺序显示
const sortedAccounts = computed(() => {
  return store.accounts
})

// 账户状态判断函数 - 基于status字段
function isAccountStopped(acc: Account): boolean {
  return acc.status === 'stopped' || acc.status === undefined || acc.status === null
}

function isAccountStarting(acc: Account): boolean {
  return acc.status === 'connecting'
}

function isAccountConnected(acc: Account): boolean {
  return acc.status === 'connected'
}

function canOperate(acc: Account): boolean {
  // 只要有status字段（任何状态）就可以操作
  return acc.status !== undefined && acc.status !== null
}

function canViewDetails(acc: Account): boolean {
  return acc.status === 'connected'
}

// 获取卡片样式类
function getAccountCardClass(acc: Account): string {
  const classes: string[] = ['account-card']
  if (acc.account_id === store.selectedAccountId) {
    classes.push('selected-account')
  }
  if (!canViewDetails(acc)) {
    classes.push('disabled-card')
  }
  return classes.join(' ')
}

// 获取状态圆点样式类
function getStatusDotClass(acc: Account): string {
  if (isAccountStopped(acc)) {
    return 'status-dot-gray'
  } else if (isAccountStarting(acc)) {
    return 'status-dot-yellow'
  } else {
    return 'status-dot-green'
  }
}

// 获取状态标签类型
function getStatusTagType(acc: Account): string {
  if (isAccountStopped(acc)) {
    return 'info'
  } else if (isAccountStarting(acc)) {
    return 'warning'
  } else {
    return 'success'
  }
}

// 获取状态文本
function getStatusText(acc: Account): string {
  if (isAccountStopped(acc)) {
    return '已停止'
  } else if (isAccountStarting(acc)) {
    return '启动中'
  } else {
    return '已连接'
  }
}

// 处理卡片点击：选中账户并进入账户详情
async function handleCardClick(acc: Account) {
  if (!canViewDetails(acc)) {
    return
  }
  await handleSelectAccount(acc.account_id)
  router.push('/account')
}

async function loadAlarmStats() {
  try {
    const result = await alarmApi.getAlarmStats()
    alarmStats.value = result || { today_total: 0, last_hour: 0, last_five_minutes: 0 }
  } catch (error: any) {
    console.error(`加载告警统计失败: ${error.message}`)
  }
}

/** 加载所有账户今日换仓进度（已完成/总条目），失败账户静默跳过 */
async function loadRotationProgress() {
  const accounts = store.accounts
  if (!accounts.length) return
  const results = await Promise.all(
    accounts.map(async acc => {
      try {
        const result = await rotationApi.getRotationInstructions(acc.account_id, { limit: 500 })
        const instructions = result.instructions || []
        return [
          acc.account_id,
          {
            completed: instructions.filter(i => i.status === 'COMPLETED').length,
            total: instructions.length
          }
        ] as const
      } catch {
        return [acc.account_id, null] as const
      }
    })
  )
  const progress: Record<string, { completed: number; total: number }> = {}
  for (const [accountId, value] of results) {
    if (value) progress[accountId] = value
  }
  rotationProgress.value = progress
}

async function handleAccountAction(cmd: any, accountId: string) {
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
      case 'restart_trader':
        await accountApi.restartTrader(targetAccountId)
        ElMessage.success('Trader已重启')
        await store.loadAllAccounts()
        break
    }
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  }
}

async function handleSelectAccount(accountId: string) {
  // 获取选中的账户配置
  const selectedAcc = store.accounts.find(a => a.account_id === accountId)

  // 检查账户状态是否为stopped
  if (!selectedAcc || selectedAcc.status === 'stopped' || !selectedAcc.status) {
    // 即使账户已停止，也要切换选中状态（用于显示卡片选中效果）
    store.switchAccount(accountId)
    return
  }

  // 检查账户是否已连接
  if (selectedAcc.status !== 'connected') {
    // 即使账户未连接，也要切换选中状态
    store.switchAccount(accountId)
    return
  }

  // 先切换选中账户（这会立即触发 currentAccount computed 的更新）
  store.switchAccount(accountId)

  // 刷新风控状态（因为WebSocket可能没有推送完整的风控数据）
  try {
    const riskStatus = await systemApi.getRiskControlStatus(accountId)
    const acc = store.accounts.find(a => a.account_id === accountId)
    if (acc) {
      acc.risk_status = riskStatus
    }
  } catch (error: any) {
    console.error('加载风控状态失败:', error)
  }

  // 刷新当前选中账户的持仓、订单、成交数据
  await Promise.all([
    store.loadPositions(accountId),
    store.loadOrders('ALIVE', accountId),
    store.loadTrades(undefined, accountId)
  ])

  // 最后刷新账户列表以确保显示最新的账户状态
  await store.loadAllAccounts()
}

onMounted(async () => {
  // 总览页需要加载所有账户的完整信息
  await store.loadAllAccounts()
  loadAlarmStats()
  loadRotationProgress()
  // 换仓进度无WebSocket推送，定时轮询刷新
  rotationTimer = window.setInterval(loadRotationProgress, 10000)
})

onUnmounted(() => {
  if (rotationTimer !== null) {
    window.clearInterval(rotationTimer)
    rotationTimer = null
  }
})

// 格式化数字
function formatNumber(num: number): string {
  return num.toFixed(2)
}

/** 获取账户换仓进度显示文本，无换仓记录时显示 -- */
function getRotationProgressText(acc: Account): string {
  const progress = rotationProgress.value[acc.account_id]
  if (!progress || !progress.total) return '--'
  return `${progress.completed}/${progress.total}`
}

/** 换仓是否全部完成（用于绿色高亮） */
function isRotationCompleted(acc: Account): boolean {
  const progress = rotationProgress.value[acc.account_id]
  return !!progress && progress.total > 0 && progress.completed >= progress.total
}
</script>

<style scoped>
.dashboard {
  padding: 0;
  min-height: 100%;
}

.mt-4 {
  margin-top: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-item {
  text-align: center;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 10px;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
}


.profit {
  color: #67c23a;
}

.loss {
  color: #f56c6c;
}

/* 多账号账户卡片样式 */
.account-cards {
  margin-bottom: 20px;
}

.account-card {
  cursor: pointer;
  transition: all 0.3s;
  border: 2px solid transparent;
}

.account-card:hover:not(.disabled-card) {
  transform: translateY(-4px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.account-card.selected-account {
  border-color: #409eff;
  background-color: #ecf5ff;
}

.account-card.disabled-card {
  opacity: 0.6;
  cursor: not-allowed;
}

.account-card.disabled-card:hover {
  transform: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.account-card-header {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 1px solid #ebeef5;
}

.account-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.account-name-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.account-card-header .account-id {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

/* 内联状态标签样式 */
.account-status-tags-inline {
  display: flex;
  gap: 4px;
  align-items: center;
  flex-wrap: wrap;
}

/* 状态圆点 */
.account-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.status-dot-gray {
  background-color: #909399;
}

.status-dot-yellow {
  background-color: #e6a23c;
}

.status-dot-green {
  background-color: #67c23a;
}

.action-btn {
  padding: 4px;
}

.account-card-stats {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.account-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.account-stat-label {
  font-size: 13px;
  color: #909399;
}

.account-stat-value {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* 移动端适配 */
@media (max-width: 767px) {
  .mb-2-mobile {
    margin-bottom: 16px;
  }

  .account-card-stats {
    gap: 6px;
  }

  .account-stat-label {
    font-size: 12px;
  }

  .account-stat-value {
    font-size: 14px;
  }

  .account-id {
    font-size: 14px;
  }

  .account-status-tags-inline .el-tag {
    font-size: 10px;
    padding: 0 4px;
    height: 18px;
  }

  .stat-label {
    font-size: 12px;
    margin-bottom: 6px;
  }

  .stat-value {
    font-size: 16px;
  }
}
</style>
