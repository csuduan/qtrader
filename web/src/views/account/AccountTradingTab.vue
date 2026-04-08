<template>
  <div class="account-trading-tab">
    <el-row :gutter="20">
      <el-col :xs="24" :lg="6">
        <el-card shadow="hover" class="quote-card">
          <template #header>
            <div class="card-header">
              <span>行情订阅</span>
              <el-space>
                <el-button @click="emit('refreshQuotes')" :loading="loading">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
                <el-button type="primary" @click="emit('showSubscribe')">
                  <el-icon><Plus /></el-icon>
                  订阅
                </el-button>
              </el-space>
            </div>
          </template>

          <div class="table-wrapper">
            <el-table
              :data="quotes"
              stripe
              v-loading="loading"
              table-layout="fixed"
              row-key="symbol"
              :default-sort="{ prop: 'symbol', order: 'ascending' }"
            >
              <template #empty>
                <el-empty description="暂无订阅行情" />
              </template>
              <el-table-column prop="symbol" label="合约" width="80" :sortable="true">
                 <template #default="{ row }">
                  {{ row.symbol}}
                </template>
              </el-table-column>

              <el-table-column prop="last_price" label="最新价" width="90">
                <template #default="{ row }">
                  {{ formatNumber(row.last_price) }}
                </template>
              </el-table-column>
              <el-table-column prop="bid_price1" label="买一价" width="90">
                <template #default="{ row }">
                  {{ formatNumber(row.bid_price1) }}
                </template>
              </el-table-column>
              <el-table-column prop="ask_price1" label="卖一价" width="90">
                <template #default="{ row }">
                  {{ formatNumber(row.ask_price1) }}
                </template>
              </el-table-column>
              <el-table-column prop="datetime" label="时间" :sortable="true">
                <template #default="{ row }">
                  {{ formatTime(row.datetime) }}
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="18">
        <el-card shadow="hover" class="order-card">
          <template #header>
            <div class="card-header">
              <el-tabs v-model="localOrderTab" type="card" @tab-change="onOrderTabChange">
                <el-tab-pane label="挂单" name="PENDING" />
                <el-tab-pane label="已成交" name="FINISHED" />
                <el-tab-pane label="废单" name="ERROR" />
              </el-tabs>
              <el-space>
                <el-button type="primary" @click="emit('showOrder')">
                  <el-icon><Plus /></el-icon>
                  报单
                </el-button>
                <el-button @click="emit('refreshOrders')" :loading="loading">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
              </el-space>
            </div>
          </template>

          <div class="table-wrapper">
            <el-table
              :data="orders"
              stripe
              v-loading="loading"
              table-layout="fixed"
              @selection-change="emit('orderSelectionChange', $event)"
            >
              <template #empty>
                <el-empty description="暂无委托单" />
              </template>
              <el-table-column prop="order_id" label="委托单ID" width="180" show-overflow-tooltip />
              <el-table-column prop="symbol" label="合约" width="120" />
              <el-table-column prop="direction" label="方向" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small">
                    {{ row.direction === 'BUY' ? '买' : '卖' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="offset" label="开平" width="80" />
              <el-table-column prop="volume_orign" label="报单手数" width="100" />
              <el-table-column prop="volume_left" label="剩余手数" width="100" />
              <el-table-column prop="limit_price" label="限价" width="100">
                <template #default="{ row }">
                  {{ row.limit_price ? formatNumber(row.limit_price) : '市价' }}
                </template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="getStatusType(row.status)" size="small">
                    {{ getStatusText(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_msg" label="最后消息" width="200" show-overflow-tooltip />
              <el-table-column prop="updated_at" label="报单时间">
                <template #default="{ row }">
                  {{ formatDateTime(row.insert_date_time) }}
                </template>
              </el-table-column>
              <el-table-column
                v-if="localOrderTab === 'PENDING'"
                label="操作"
                width="100"
                fixed="right"
              >
                <template #default="{ row }">
                  <el-button
                    type="danger"
                    size="small"
                    @click="emit('cancelOrder', row.order_id)"
                  >
                    撤单
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Order, Quote } from '@/types'

const props = defineProps<{
  loading: boolean
  quotes: Quote[]
  orders: Order[]
  orderTab: 'PENDING' | 'FINISHED' | 'ERROR'
}>()

const emit = defineEmits<{
  refreshQuotes: []
  showSubscribe: []
  refreshOrders: []
  showOrder: []
  cancelOrder: [orderId: string]
  orderSelectionChange: [selection: Order[]]
  'update:orderTab': [tab: 'PENDING' | 'FINISHED' | 'ERROR']
}>()

const localOrderTab = computed({
  get: () => props.orderTab,
  set: (val) => emit('update:orderTab', val)
})

function onOrderTabChange() {
  emit('refreshOrders')
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

function formatTime(datetime: string | number): string {
  const date = typeof datetime === 'string'
    ? new Date(datetime)
    : new Date(datetime * 1000)
  return date.toTimeString().slice(0, 8)
}

function getStatusType(status: string): string {
  switch (status) {
    case 'ALIVE':
      return 'warning'
    case 'FINISHED':
      return 'success'
    case 'CANCELED':
      return 'info'
    case 'REJECTED':
      return 'danger'
    default:
      return 'info'
  }
}

function getStatusText(status: string): string {
  switch (status) {
    case 'ALIVE':
      return '挂单中'
    case 'FINISHED':
      return '已成交'
    case 'CANCELED':
      return '已撤单'
    case 'REJECTED':
      return '废单'
    default:
      return status
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

.quote-card,
.order-card {
  margin-bottom: 12px;
}
</style>
