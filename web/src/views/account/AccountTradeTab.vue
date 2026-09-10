<template>
  <div class="account-trade-tab">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>成交记录</span>
          <el-space>
            <el-date-picker
              v-model="localDateFilter"
              type="date"
              placeholder="选择日期"
              format="YYYY-MM-DD"
              value-format="YYYY-MM-DD"
              clearable
            />
            <el-button type="primary" @click="emit('refresh')" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </el-space>
        </div>
      </template>

      <div class="table-wrapper">
        <el-table
          :data="trades"
          data-testid="trades-table"
          stripe
          v-loading="loading"
          :size="isMobile ? 'small' : 'default'"
        >
          <template #empty>
            <el-empty description="暂无成交记录" />
          </template>
          <el-table-column v-if="!isMobile" prop="trade_id" label="成交ID" width="180" show-overflow-tooltip />
          <el-table-column prop="symbol" label="合约" width="80" />
          <el-table-column prop="direction" label="方向" :width="isMobile ? 50 : 80">
            <template #default="{ row }">
              <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small">
                {{ row.direction === 'BUY' ? '买' : '卖' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="offset" label="开平" :width="isMobile ? 60 : 80" />
          <el-table-column prop="price" label="成交价" :width="isMobile ? 70 : 100">
            <template #default="{ row }">
              {{ formatNumber(row.price) }}
            </template>
          </el-table-column>
          <el-table-column prop="volume" label="手数" :width="isMobile ? 50 : 80" />
          <el-table-column v-if="!isMobile" prop="order_id" label="委托单ID" width="180" show-overflow-tooltip />
          <el-table-column prop="created_at" label="成交时间" :min-width="isMobile ? 120 : 160">
            <template #default="{ row }">
              {{ formatDateTime(row.trade_date_time) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import type { Trade } from '@/types'

const props = defineProps<{
  loading: boolean
  trades: Trade[]
  dateFilter: string | undefined
}>()

const emit = defineEmits<{
  refresh: []
  'update:dateFilter': [date: string | undefined]
}>()

const localDateFilter = computed({
  get: () => props.dateFilter,
  set: (val) => emit('update:dateFilter', val || new Date().toISOString().split('T')[0])
})

const isMobile = ref(false)
const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 768
}

onMounted(() => {
  updateIsMobile()
  window.addEventListener('resize', updateIsMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateIsMobile)
})

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
</style>
