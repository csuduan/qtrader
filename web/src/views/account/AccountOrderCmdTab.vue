<template>
  <div class="account-order-cmd-tab">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>报单指令</span>
          <el-space>
            <el-radio-group v-model="localStatus" @change="emit('refresh')">
              <el-radio-button label="active">未完成</el-radio-button>
              <el-radio-button label="finished">已完成</el-radio-button>
            </el-radio-group>
            <el-button type="primary" @click="emit('refresh')" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </el-space>
        </div>
      </template>

      <div class="table-wrapper">
        <el-table :data="sortedOrderCmds" stripe v-loading="loading">
          <template #empty>
            <el-empty description="暂无报单指令" />
          </template>
          <el-table-column prop="cmd_id" label="指令ID" width="180" show-overflow-tooltip />
          <el-table-column prop="source" label="来源" width="150" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.source || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="symbol" label="合约" width="120" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="getOrderCmdStatusType(row.status)" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="volume" label="总手数" width="100" />
          <el-table-column prop="filled_volume" label="已成交手数" width="120" />
          <el-table-column prop="limit_price" label="限价" width="100">
            <template #default="{ row }">
              {{ row.limit_price ? formatNumber(row.limit_price) : '市价' }}
            </template>
          </el-table-column>
          <el-table-column prop="direction" label="方向" width="80">
            <template #default="{ row }">
              <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small" v-if="row.direction">
                {{ row.direction === 'BUY' ? '买' : '卖' }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="offset" label="开平" width="80">
            <template #default="{ row }">
              {{ row.offset || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="started_at" label="开始时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.started_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="finished_at" label="结束时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.finished_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="total_orders" label="总报单数" width="100" />
          <el-table-column prop="finish_reason" label="结束原因" width="180" show-overflow-tooltip />
          <el-table-column
            v-if="localStatus === 'active'"
            label="操作"
            width="100"
            fixed="right"
          >
            <template #default="{ row }">
              <el-button
                type="danger"
                size="small"
                @click="emit('cancelOrderCmd', row.cmd_id)"
                :loading="cancellingCmdId === row.cmd_id"
              >
                取消
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { OrderCmd } from '@/types'

const props = defineProps<{
  loading: boolean
  orderCmds: OrderCmd[]
  status: 'active' | 'finished'
  cancellingCmdId: string | null
}>()

const emit = defineEmits<{
  refresh: []
  cancelOrderCmd: [cmdId: string]
  'update:status': [status: 'active' | 'finished']
}>()

const localStatus = computed({
  get: () => props.status,
  set: (val) => emit('update:status', val)
})

// 按开始时间倒序排序的报单指令
const sortedOrderCmds = computed(() => {
  if (!props.orderCmds || props.orderCmds.length === 0) return []
  return [...props.orderCmds].sort((a, b) => {
    const timeA = a.started_at ? new Date(a.started_at).getTime() : 0
    const timeB = b.started_at ? new Date(b.started_at).getTime() : 0
    return timeB - timeA
  })
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

function getOrderCmdStatusType(status: string): string {
  switch (status) {
    case 'RUNNING':
      return 'success'
    case 'FINISHED':
      return 'info'
    case 'CANCELED':
      return 'warning'
    default:
      return 'info'
  }
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
