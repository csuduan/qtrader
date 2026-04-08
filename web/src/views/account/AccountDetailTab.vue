<template>
  <div class="account-detail-tab">
    <el-card shadow="hover" v-if="store.currentAccount">
      <template #header>
        <div class="card-header">
          <span>账户信息</span>
          <div>
            <el-button type="primary" @click="emit('refresh')" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-descriptions :column="descColumn" border>
        <el-descriptions-item label="用户ID">{{ store.currentAccount.user_id || '-'}}</el-descriptions-item>
        <el-descriptions-item label="经纪商">
          {{ store.currentAccount.broker_name || '-' }}
          <el-tag v-if="store.currentAccount.broker_type" size="small" style="margin-left: 8px">
            {{ getBrokerTypeName(store.currentAccount.broker_type) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="总资产">
          <span class="balance">¥{{ formatNumber(store.currentAccount.balance) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="静态权益">
          <span class="available">¥{{ formatNumber(store.currentAccount.static_balance) }}</span>
        </el-descriptions-item>

        <el-descriptions-item label="持仓盈亏">
          <span :class="store.currentAccount.position_profit >= 0 ? 'profit' : 'loss'">
            ¥{{ formatNumber(store.currentAccount.position_profit) }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="平仓盈亏">
          <span :class="store.currentAccount.close_profit >= 0 ? 'profit' : 'loss'">
            ¥{{ formatNumber(store.currentAccount.close_profit) }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="保证金占用">
          ¥{{ formatNumber(store.currentAccount.margin) }}
           <el-tag :type="store.currentAccount.risk_ratio > 1 ? 'danger' : 'success'">
            {{ formatNumber(store.currentAccount.risk_ratio*100) }}%
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(store.currentAccount.updated_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="hover" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>持仓列表</span>
          <el-button @click="emit('refreshPositions')" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <div class="table-wrapper">
        <el-table
          :data="store.currentPositions"
          stripe
          v-loading="loading"
          table-layout="fixed"
        >
          <template #empty>
            <el-empty description="暂无持仓" />
          </template>
          <el-table-column prop="symbol" label="合约" width="150" fixed>
            <template #default="{ row }">
              {{ row.symbol }}
            </template>
          </el-table-column>
          <el-table-column label="多头持仓" width="100">
            <template #default="{ row }">
              <span v-if="row.pos_long > 0" class="long">{{ row.pos_long }}</span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="空头持仓" width="100">
            <template #default="{ row }">
              <span v-if="row.pos_short > 0" class="short">{{ row.pos_short }}</span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="多头均价" width="110">
            <template #default="{ row }">
              {{ row.pos_long > 0 ? formatNumber(row.hold_price_long) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="空头均价" width="110">
            <template #default="{ row }">
              {{ row.pos_short > 0 ? formatNumber(row.hold_price_short) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="保证金" width="110">
            <template #default="{ row }">
              ¥{{ formatNumber((row.margin_long || 0) + (row.margin_short || 0)) }}
            </template>
          </el-table-column>
          <el-table-column label="持仓盈亏" width="130">
            <template #default="{ row }">
              <span :class="(row.hold_profit_long || 0) + (row.hold_profit_short || 0) >= 0 ? 'profit' : 'loss'">
                ¥{{ formatNumber((row.hold_profit_long || 0) + (row.hold_profit_short || 0)) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="平仓盈亏" width="130">
            <template #default="{ row }">
              <span :class="(row.close_profit_long || 0) + (row.close_profit_short || 0) >= 0 ? 'profit' : 'loss'">
                ¥{{ formatNumber((row.close_profit_long || 0) + (row.close_profit_short || 0)) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="updated_at" label="更新时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.updated_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作"  fixed="right">
            <template #default="{ row }">
              <el-button
                type="danger"
                size="small"
                :disabled="row.pos_long <= 0"
                @click="emit('closePosition', row, 'SELL')"
              >
                平多
              </el-button>
              <el-button
                type="primary"
                size="small"
                :disabled="row.pos_short <= 0"
                @click="emit('closePosition', row, 'BUY')"
              >
                平空
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useStore } from '@/stores'
import type { Position } from '@/types'

const store = useStore()
const descColumn = ref(2)

const props = defineProps<{
  loading: boolean
}>()

const emit = defineEmits<{
  refresh: []
  refreshPositions: []
  closePosition: [position: Position, direction: 'BUY' | 'SELL']
}>()

function updateDescColumn() {
  descColumn.value = window.innerWidth <= 768 ? 1 : 2
}

function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '0.00'
  return num.toFixed(2)
}

function formatDateTime(datetime: string | number | null | undefined): string {
  if (!datetime) return '-'
  const date = typeof datetime === 'number'
    ? new Date(datetime * 1000)
    : new Date(datetime)
  return date.toLocaleString('zh-CN')
}

function getBrokerTypeName(type: string | null): string {
  const typeMap: Record<string, string> = {
    'tq': '天勤',
    'sim': '模拟',
    'kq': '快期',
    'ctp': 'CTP',
  }
  return typeMap[type || ''] || type || ''
}

onMounted(() => {
  updateDescColumn()
  window.addEventListener('resize', updateDescColumn)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateDescColumn)
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.table-wrapper {
  width: 100%;
  overflow-x: auto;
}

.table-wrapper .el-table {
  min-width: 600px;
}

.balance,
.available {
  font-size: 18px;
  font-weight: 600;
}

.profit {
  color: #67c23a;
  font-weight: 600;
}

.loss {
  color: #f56c6c;
  font-weight: 600;
}

.long {
  color: #67c23a;
  font-weight: 600;
}

.short {
  color: #f56c6c;
  font-weight: 600;
}
</style>
