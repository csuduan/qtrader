<template>
  <div class="account-tabs">
    <el-card shadow="hover" v-if="store.currentAccount">
      <template #header>
        <div class="card-header">
          <span>账户信息</span>
          <el-button type="primary" @click="loadAccountData" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="用户ID">{{ store.currentAccount.user_id || '-'}}</el-descriptions-item>
        <el-descriptions-item label="经纪商">
          {{ store.currentAccount.broker_name || '-' }}
          <el-tag v-if="store.currentAccount.broker_type" size="small" style="margin-left: 8px">
            {{ getBrokerTypeName(store.currentAccount.broker_type) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="币种">{{ store.currentAccount.currency }}</el-descriptions-item>
        <el-descriptions-item label="风险率">
          <el-tag :type="store.currentAccount.risk_ratio > 1 ? 'danger' : 'success'">
            {{ formatNumber(store.currentAccount.risk_ratio) }}%
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="总资产" :span="2">
          <span class="balance">¥{{ formatNumber(store.currentAccount.balance) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="可用资金">
          <span class="available">¥{{ formatNumber(store.currentAccount.available) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="保证金占用">
          ¥{{ formatNumber(store.currentAccount.margin) }}
        </el-descriptions-item>
        <el-descriptions-item label="浮动盈亏">
          <span :class="store.currentAccount.float_profit >= 0 ? 'profit' : 'loss'">
            ¥{{ formatNumber(store.currentAccount.float_profit) }}
          </span>
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
        <el-descriptions-item label="更新时间">{{ formatDateTime(store.currentAccount.updated_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="hover" style="margin-top: 20px;">
      <template #header>
        <div class="card-header">
          <span>持仓列表</span>
          <el-button @click="loadPositionData" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-table
        :data="store.currentPositions"
        stripe
        v-loading="loading"
        table-layout="fixed"
      >
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
        <el-table-column label="多头开仓价" width="110">
          <template #default="{ row }">
            {{ row.pos_long > 0 ? formatNumber(row.open_price_long) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="空头开仓价" width="110">
          <template #default="{ row }">
            {{ row.pos_short > 0 ? formatNumber(row.open_price_short) : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="margin" label="保证金" width="110">
          <template #default="{ row }">
            ¥{{ formatNumber(row.margin) }}
          </template>
        </el-table-column>
        <el-table-column prop="float_profit" label="浮动盈亏" width="130">
          <template #default="{ row }">
            <span :class="row.float_profit >= 0 ? 'profit' : 'loss'">
              ¥{{ formatNumber(row.float_profit) }}
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
              @click="handleClosePosition(row, 'SELL')"
            >
              平多
            </el-button>
            <el-button
              type="primary"
              size="small"
              :disabled="row.pos_short <= 0"
              @click="handleClosePosition(row, 'BUY')"
            >
              平空
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="store.currentPositions.length === 0" description="暂无持仓" />
    </el-card>

    <el-dialog v-model="showCloseDialog" title="确认平仓" width="500px">
      <el-form label-width="100px">
        <el-form-item label="合约">
          {{ closeForm.symbol }}
        </el-form-item>
        <el-form-item label="方向">
          <el-tag :type="closeForm.direction === 'BUY' ? 'success' : 'danger'" size="small">
            {{ closeForm.direction === 'BUY' ? '卖出' : '买入' }}
          </el-tag>
        </el-form-item>
        <el-form-item label="开平">
          <el-select v-if="closeForm.exchange_id?.toUpperCase() === 'SHFE'" v-model="closeForm.offset" style="width: 100%">
            <el-option label="平昨" value="CLOSE" />
            <el-option label="平今" value="CLOSETODAY" />
          </el-select>
          <span v-else>{{ closeForm.offset === 'OPEN' ? '开仓' : closeForm.offset === 'CLOSE' ? '平仓' : '平今' }}</span>
        </el-form-item>
        <el-form-item label="平仓手数">
          <el-input-number
            v-model="closeForm.volume"
            :min="1"
            :max="closeForm.maxVolume"
            controls-position="right"
            style="width: 100%"
          />
          <span class="text-sm text-gray-500 ml-2">最大可用: {{ closeForm.maxVolume }} 手</span>
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number
            v-model="closeForm.price"
            :min="0"
            :precision="2"
            placeholder="0表示市价"
            controls-position="right"
            style="width: 100%"
          />
          <span class="ml-2 text-sm text-gray-500">留空或0为市价</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCloseDialog = false">取消</el-button>
        <el-button type="danger" @click="handleClosePositionConfirm" :loading="false">
          确认平仓
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { positionApi } from '@/api'
import type { Position } from '@/types'

const store = useStore()
const loading = ref(false)
const showCloseDialog = ref(false)

const closeForm = reactive({
  symbol: '',
  exchange_id: '',
  direction: 'BUY',
  offset: 'CLOSE',
  volume: 0,
  maxVolume: 0,
  price: 0
})

async function loadAccountData() {
  loading.value = true
  try {
    await store.loadAllAccounts()
  } finally {
    loading.value = false
  }
}

async function loadPositionData() {
  loading.value = true
  try {
    await store.loadPositions(store.selectedAccountId || undefined)
  } finally {
    loading.value = false
  }
}

function handleClosePosition(position: Position, direction: 'BUY' | 'SELL') {
  const volume = direction === 'SELL' ? position.pos_long : position.pos_short
  if (volume <= 0) return

  closeForm.symbol = position.instrument_id
  closeForm.exchange_id = position.exchange_id
  closeForm.direction = direction
  closeForm.offset = 'CLOSE'
  closeForm.volume = volume
  closeForm.maxVolume = volume
  closeForm.price = 0

  showCloseDialog.value = true
}

async function handleClosePositionConfirm() {
  if (!store.selectedAccountId) {
    ElMessage.error('请先选择账户')
    return
  }
  try {
    await positionApi.closePosition({
      symbol: closeForm.symbol,
      direction: closeForm.direction,
      offset: closeForm.offset,
      volume: closeForm.volume,
      price: closeForm.price,
      account_id: store.selectedAccountId
    })
    ElMessage.success('平仓成功')
    showCloseDialog.value = false
    await loadPositionData()
  } catch (error: any) {
    ElMessage.error(`平仓失败: ${error.message}`)
    showCloseDialog.value = false
  }
}

function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '0.00'
  return num.toFixed(2)
}

function formatDateTime(datetime: string | number): string {
  const date = typeof datetime === 'number'
    ? new Date(datetime * 1000)
    : new Date(datetime)
  return date.toLocaleString('zh-CN')
}

function getBrokerTypeName(type: string | null): string {
  const typeMap: Record<string, string> = {
    'real': '实盘',
    'sim': '模拟',
    'kq': '快期'
  }
  return typeMap[type || ''] || type || ''
}

onMounted(async () => {
  await loadAccountData()
  await loadPositionData()
})
</script>

<style scoped>
.account-tabs {
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
