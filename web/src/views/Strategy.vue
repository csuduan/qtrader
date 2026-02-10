<template>
  <div class="strategy">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>策略管理</span>
          <el-space>
            <el-button type="primary" @click="handleReplayAll" :loading="replayAllLoading">
              <el-icon><VideoPlay /></el-icon>
              回播
            </el-button>
            <el-button @click="loadStrategies" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </el-space>
        </div>
      </template>

      <el-table :data="strategies" stripe v-loading="loading" table-layout="auto">
        <el-table-column prop="strategy_id" label="策略ID" width="180" fixed />
        <el-table-column prop="config.symbol" label="合约" width="120" />
        <el-table-column prop="config.bar" label="时间类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.config.bar || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" width="100">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              @change="handleToggleEnabled(row.strategy_id, row.enabled)"
              :loading="row.toggleLoading"
            />
          </template>
        </el-table-column>
        <el-table-column label="暂停开仓" width="100">
          <template #default="{ row }">
            <el-checkbox
              v-model="row.opening_paused"
              @change="handleToggleOpeningPaused(row.strategy_id, row.opening_paused)"
            />
          </template>
        </el-table-column>
        <el-table-column label="暂停平仓" width="100">
          <template #default="{ row }">
            <el-checkbox
              v-model="row.closing_paused"
              @change="handleToggleClosingPaused(row.strategy_id, row.closing_paused)"
            />
          </template>
        </el-table-column>
        <el-table-column label="信号" width="100">
          <template #default="{ row }">
            <el-tooltip v-if="row.signal && row.signal.side !== 0" placement="left" :show-after="200">
              <template #content>
                <div class="signal-detail">
                  <div>方向: <span :class="row.signal.side > 0 ? 'text-long' : 'text-short'">{{ row.signal.side > 0 ? '多头' : '空头' }}</span></div>
                  <div v-if="row.signal.entry_price">入场价: {{ row.signal.entry_price.toFixed(2) }}</div>
                  <div v-if="row.signal.entry_time">入场时间: {{ formatDateTime(row.signal.entry_time) }}</div>
                  <div v-if="row.signal.entry_volume">目标手数: {{ row.signal.entry_volume }}</div>
                  <div v-if="row.signal.pos_volume">持仓手数: {{ row.signal.pos_volume }}</div>
                  <div v-if="row.signal.pos_price">持仓均价: {{ row.signal.pos_price.toFixed(2) }}</div>
                  <div v-if="row.signal.exit_time" class="exit-info">
                    <div>退出价: {{ row.signal.exit_price?.toFixed(2) || '-' }}</div>
                    <div>退出时间: {{ formatDateTime(row.signal.exit_time) }}</div>
                    <div>退出原因: {{ getExitReasonText(row.signal.exit_reason) }}</div>
                  </div>
                </div>
              </template>
              <el-tag :type="row.signal.side > 0 ? 'danger' : 'primary'" size="small">
                {{ row.signal.side > 0 ? '多' : '空' }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else type="info" size="small">无</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="交易状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getTradingStatusType(row.trading_status)" size="small">
              {{ row.trading_status || '无' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              @click="navigateToDetails(row.strategy_id)"
            >
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="strategies.length === 0" description="暂无策略" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useStore } from '@/stores'
import { strategyApi } from '@/api'
import type { StrategyRes } from '@/types'

// 扩展 StrategyRes 类型，添加 toggleLoading 属性
interface StrategyWithLoading extends StrategyRes {
  toggleLoading?: boolean
}

const router = useRouter()
const store = useStore()
const loading = ref(false)
const strategies = ref<StrategyWithLoading[]>([])
const replayAllLoading = ref(false)

function navigateToDetails(strategyId: string) {
  router.push(`/strategy/${strategyId}`)
}

function formatDateTime(dateStr: string | undefined): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function getExitReasonText(reason: string | undefined): string {
  const reasonMap: Record<string, string> = {
    'TP': '止盈',
    'SL': '止损',
    'FORCE': '强制平仓'
  }
  return reasonMap[reason || ''] || reason || '-'
}

function getTradingStatusType(status: string | undefined): string {
  const typeMap: Record<string, string> = {
    '无': 'info',
    '开仓中': 'primary',
    '平仓中': 'warning',
    '持仓': 'success'
  }
  return typeMap[status || ''] || 'info'
}

async function loadStrategies() {
  loading.value = true
  try {
    strategies.value = await strategyApi.getStrategies(store.selectedAccountId || undefined)
  } catch (error: any) {
    ElMessage.error(`加载策略失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function handleToggleEnabled(strategyId: string, enabled: boolean) {
  const strategy = strategies.value.find(s => s.strategy_id === strategyId)
  if (strategy) {
    strategy.toggleLoading = true
  }
  try {
    if (enabled) {
      await strategyApi.enableStrategy(strategyId, store.selectedAccountId || undefined)
      ElMessage.success('策略已启用')
    } else {
      await strategyApi.disableStrategy(strategyId, store.selectedAccountId || undefined)
      ElMessage.success('策略已禁用')
    }
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
    if (strategy) {
      strategy.toggleLoading = false
    }
  }
}

async function handleToggleOpeningPaused(strategyId: string, paused: boolean) {
  try {
    await strategyApi.setTradingStatus(
      strategyId,
      { opening_paused: paused },
      store.selectedAccountId || undefined
    )
    ElMessage.success(paused ? '已暂停开仓' : '已恢复开仓')
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  }
}

async function handleToggleClosingPaused(strategyId: string, paused: boolean) {
  try {
    await strategyApi.setTradingStatus(
      strategyId,
      { closing_paused: paused },
      store.selectedAccountId || undefined
    )
    ElMessage.success(paused ? '已暂停平仓' : '已恢复平仓')
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  }
}

async function handleReplayAll() {
  try {
    await ElMessageBox.confirm(
      '当前只支持回播当日bar，流程：暂停策略 -> 重置策略 -> 回播当日bar -> 恢复策略。\n是否继续？',
      '确认回播当日bar',
      {
        confirmButtonText: '确认回播',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }

  replayAllLoading.value = true
  try {
    const result = await strategyApi.replayAllStrategies(store.selectedAccountId || undefined)
    ElMessage.success(`回播完成，共回播 ${result.replayed_count} 个策略`)
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`回播策略失败: ${error.message}`)
  } finally {
    replayAllLoading.value = false
  }
}

onMounted(async () => {
  loadStrategies()
})
</script>

<style scoped>
.strategy {
  padding: 0;
  width: 100%;
}

.el-table {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.signal-detail {
  font-size: 12px;
  line-height: 1.8;
  min-width: 150px;
}

.signal-detail > div {
  display: block;
}

.signal-detail .exit-info {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color);
}

.text-long {
  color: var(--el-color-danger);
  font-weight: 500;
}

.text-short {
  color: var(--el-color-primary);
  font-weight: 500;
}

.unit-label {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
