<template>
  <div class="dashboard">
    <!-- 账户卡片列表 -->
    <div class="account-cards">
      <el-row :gutter="20">
        <el-col :span="6" v-for="acc in sortedAccounts" :key="acc.account_id">
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
                    <el-tag v-if="!isAccountConnected(acc)" :type="getStatusTagType(acc)" size="small">
                      {{ getStatusText(acc) }}
                    </el-tag>
                    <!-- 已连接状态：只显示额外标签，不显示主标签 -->
                    <template v-if="isAccountConnected(acc)">
                      <el-tag v-if="acc.gateway_connected" type="success" size="small">已连接</el-tag>
                      <el-tag v-if="!acc.gateway_connected" type="info" size="small">已断开</el-tag>
                      <el-tag v-if="acc.trade_paused" type="warning" size="small">暂停交易</el-tag>
                      <el-tag v-if="!acc.trade_paused" type="success" size="small">可交易</el-tag>
                    </template>
                  </div>
                </div>
                <el-dropdown trigger="click" @command="(cmd) => handleAccountAction(cmd, acc.account_id)" @click.stop>
                  <el-button circle size="small" class="action-btn" :disabled="!canOperate(acc)">
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <!-- 已连接状态：显示连接网关、断开网关、暂停交易、恢复交易 -->
                      <template v-if="isAccountConnected(acc)">
                        <el-dropdown-item
                          :command="{ action: 'connect_gateway', accountId: acc.account_id }"
                          v-if="!acc.gateway_connected"
                        >
                          <el-icon><Connection /></el-icon>
                          连接网关
                        </el-dropdown-item>
                        <el-dropdown-item
                          :command="{ action: 'disconnect_gateway', accountId: acc.account_id }"
                          v-if="acc.gateway_connected"
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
                <div class="account-stat-label">浮动盈亏</div>
                <div class="account-stat-value" :class="(acc.float_profit || 0) >= 0 ? 'profit' : 'loss'">
                  ¥{{ formatNumber(acc.float_profit || 0) }}
                </div>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 分割线 -->
    <el-divider />

    <!-- 统计卡片 -->
    <el-row :gutter="20" class="mt-4">
      <!-- 统一使用当前选中账户的数据 -->
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="总资产" :value="store.currentAccount?.balance || 0" :precision="2" prefix="¥" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="可用资金" :value="store.currentAccount?.available || 0" :precision="2" prefix="¥" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic
            title="持仓数量"
            :value="store.currentPositions.length"
            suffix="个"
          />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic
            title="活跃委托"
            :value="store.currentOrders.filter(o => o.status === 'ALIVE').length"
            suffix="单"
          />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <!-- 盈亏统计 -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>盈亏统计</span>
            </div>
          </template>
          <!-- 统一使用当前选中账户的数据 -->
          <div v-if="store.currentAccount">
            <el-row :gutter="20">
              <el-col :span="12">
                <div class="stat-item">
                  <div class="stat-label">浮动盈亏</div>
                  <div class="stat-value" :class="(store.currentAccount.float_profit || 0) >= 0 ? 'profit' : 'loss'">
                    ¥{{ formatNumber(store.currentAccount.float_profit || 0) }}
                  </div>
                </div>
              </el-col>
              <el-col :span="12">
                <div class="stat-item">
                  <div class="stat-label">平仓盈亏</div>
                  <div class="stat-value" :class="(store.currentAccount.close_profit || 0) >= 0 ? 'profit' : 'loss'">
                    ¥{{ formatNumber(store.currentAccount.close_profit || 0) }}
                  </div>
                </div>
              </el-col>
            </el-row>
          </div>
          <div v-else class="stat-item">
            <div class="stat-value" style="color: #909399;">请选择账户</div>
          </div>
        </el-card>
      </el-col>

      <!-- 风控统计 -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>今日风控</span>
            </div>
          </template>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-progress
                :percentage="getOrderPercentage()"
                :color="getProgressColor(getOrderPercentage())"
                :stroke-width="20"
              />
              <div class="progress-label">
                今日报单: {{ currentRiskStatus.daily_order_count }} / {{ currentRiskStatus.max_daily_orders }}
              </div>
            </el-col>
            <el-col :span="12">
              <el-progress
                :percentage="getCancelPercentage()"
                :color="getProgressColor(getCancelPercentage())"
                :stroke-width="20"
              />
              <div class="progress-label">
                今日撤单: {{ currentRiskStatus.daily_cancel_count }} / {{ currentRiskStatus.max_daily_cancels }}
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>

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
          <el-row :gutter="20">
            <el-col :span="8">
              <div class="stat-item">
                <div class="stat-label">今日总告警</div>
                <div class="stat-value" :class="alarmStats.today_total > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.today_total }}
                </div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="stat-item">
                <div class="stat-label">最近1小时告警</div>
                <div class="stat-value" :class="alarmStats.last_hour > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.last_hour }}
                </div>
              </div>
            </el-col>
            <el-col :span="8">
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
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { alarmApi, systemApi, accountApi } from '@/api'
import type { RiskControlStatus, Account } from '@/types'

const store = useStore()
const alarmStats = ref({ today_total: 0, last_hour: 0, last_five_minutes: 0 })

const currentRiskStatus = computed<RiskControlStatus>(() => {
  return store.currentAccount?.risk_status || {
    daily_order_count: 0,
    daily_cancel_count: 0,
    max_daily_orders: 100,
    max_daily_cancels: 50,
    max_order_volume: 50,
    max_split_volume: 5,
    order_timeout: 5,
    remaining_orders: 100,
    remaining_cancels: 50
  }
})

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

// 处理卡片点击
async function handleCardClick(acc: Account) {
  if (!canViewDetails(acc)) {
    return
  }
  await handleSelectAccount(acc.account_id)
}

async function loadAlarmStats() {
  try {
    const result = await alarmApi.getAlarmStats(store.selectedAccountId || undefined)
    alarmStats.value = result || { today_total: 0, last_hour: 0, last_five_minutes: 0 }
  } catch (error: any) {
    console.error(`加载告警统计失败: ${error.message}`)
  }
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
    store.loadOrders(undefined, accountId),
    store.loadTrades(undefined, accountId)
  ])

  // 最后刷新账户列表以确保显示最新的账户状态
  await store.loadAllAccounts()
}

onMounted(async () => {
  // App.vue 已经在 loadAllData 中加载了账户列表，这里不需要重复加载
  loadAlarmStats()
})

// 格式化数字
function formatNumber(num: number): string {
  return num.toFixed(2)
}

// 格式化日期时间
function formatDateTime(datetime: string): string {
  return new Date(datetime).toLocaleString('zh-CN')
}

// 计算报单百分比
function getOrderPercentage(): number {
  if (currentRiskStatus.value.max_daily_orders === 0) return 0
  const percentage = (currentRiskStatus.value.daily_order_count / currentRiskStatus.value.max_daily_orders) * 100
  return parseFloat(percentage.toFixed(1))
}

// 计算撤单百分比
function getCancelPercentage(): number {
  if (currentRiskStatus.value.max_daily_cancels === 0) return 0
  const percentage = (currentRiskStatus.value.daily_cancel_count / currentRiskStatus.value.max_daily_cancels) * 100
  return parseFloat(percentage.toFixed(1))
}

// 进度条颜色
function getProgressColor(percentage: number): string {
  if (percentage >= 80) return '#f56c6c'
  if (percentage >= 60) return '#e6a23c'
  return '#67c23a'
}
</script>

<style scoped>
.dashboard {
  padding: 0;
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

.progress-label {
  text-align: center;
  margin-top: 10px;
  font-size: 12px;
  color: #606266;
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
</style>
