<template>
  <div class="strategy">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>策略管理</span>
          <el-space>
            <el-button type="success" @click="handleStartAll" :loading="loading">
              <el-icon><VideoPlay /></el-icon>
              启动
            </el-button>
            <el-button type="warning" @click="handleStopAll" :loading="loading">
              <el-icon><VideoPause /></el-icon>
              停止
            </el-button>
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

      <el-table :data="strategies" stripe v-loading="loading" table-layout="fixed">
        <el-table-column prop="strategy_id" label="策略ID" width="150" />
        <!-- <el-table-column prop="config.strategy_type" label="策略类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">
              {{ row.config.strategy_type === 'bar' ? 'K线策略' : row.config.strategy_type === 'tick' ? 'Tick策略' : '混合策略' }}
            </el-tag>
          </template>
        </el-table-column> -->
        <el-table-column prop="config.symbol" label="合约" width="120">
          <template #default="{ row }">
            {{ row.config.symbol || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="config.exchange" label="交易所" width="100">
          <template #default="{ row }">
            {{ row.config.exchange || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="运行状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.active ? 'success' : 'info'" size="small">
              {{ row.active ? '运行中' : '已停止' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="config.volume_per_trade" label="手数/次" width="90" />
        <el-table-column prop="config.max_position" label="最大持仓" width="90" />
        <el-table-column label="策略参数" min-width="200">
          <template #default="{ row }">
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item v-if="row.config.rsi_period !== undefined" label="RSI周期">
                {{ row.config.rsi_period }}
              </el-descriptions-item>
              <el-descriptions-item v-if="row.config.rsi_long_threshold !== undefined" label="多头阈值">
                {{ row.config.rsi_long_threshold }}
              </el-descriptions-item>
              <el-descriptions-item v-if="row.config.rsi_short_threshold !== undefined" label="空头阈值">
                {{ row.config.rsi_short_threshold }}
              </el-descriptions-item>
              <el-descriptions-item v-if="row.config.take_profit_pct !== undefined" label="止盈%">
                {{ (row.config.take_profit_pct * 100).toFixed(1) }}%
              </el-descriptions-item>
              <el-descriptions-item v-if="row.config.stop_loss_pct !== undefined" label="止损%">
                {{ (row.config.stop_loss_pct * 100).toFixed(1) }}%
              </el-descriptions-item>
            </el-descriptions>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="!row.active"
              type="success"
              size="small"
              @click="handleStartStrategy(row.strategy_id)"
            >
              启动
            </el-button>
            <el-button
              v-else
              type="warning"
              size="small"
              @click="handleStopStrategy(row.strategy_id)"
            >
              停止
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="strategies.length === 0" description="暂无策略" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useStore } from '@/stores'
import { strategyApi } from '@/api'
import type { StrategyRes } from '@/types'

const store = useStore()
const loading = ref(false)
const strategies = ref<StrategyRes[]>([])
const replayAllLoading = ref(false)

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

async function handleStartStrategy(strategyId: string) {
  try {
    await strategyApi.startStrategy(strategyId, store.selectedAccountId || undefined)
    ElMessage.success(`策略 ${strategyId} 已启动`)
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`启动策略失败: ${error.message}`)
  }
}

async function handleStopStrategy(strategyId: string) {
  try {
    await strategyApi.stopStrategy(strategyId, store.selectedAccountId || undefined)
    ElMessage.success(`策略 ${strategyId} 已停止`)
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`停止策略失败: ${error.message}`)
  }
}

async function handleStartAll() {
  try {
    await strategyApi.startAllStrategies(store.selectedAccountId || undefined)
    ElMessage.success('所有策略已启动')
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`启动策略失败: ${error.message}`)
  }
}

async function handleStopAll() {
  try {
    await strategyApi.stopAllStrategies(store.selectedAccountId || undefined)
    ElMessage.success('所有策略已停止')
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`停止策略失败: ${error.message}`)
  }
}

function formatNumber(num: number): string {
  return num.toFixed(2)
}

async function handleReplayAll() {
  // 弹出确认对话框
  try {
    await ElMessageBox.confirm(
      '当前只支持bar回播，回播会重置策略，并从当前交易日的初始bar开始推送。是否继续？',
      '确认回播全部策略',
      {
        confirmButtonText: '确认回播',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    // 用户取消
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
</style>
