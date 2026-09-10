<template>
  <div class="account-contract-tab">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>合约信息</span>
          <el-space>
            <el-select v-model="localFilter.exchange_id" placeholder="交易所" clearable style="width: 120px" @change="emit('refresh')">
              <el-option label="全部" value="" />
              <el-option v-for="ex in exchanges" :key="ex.exchange_id" :label="`${ex.exchange_id} (${ex.contract_count})`" :value="ex.exchange_id" />
            </el-select>
            <el-input v-model="localFilter.symbol_keyword" placeholder="合约代码" clearable style="width: 150px" @keyup.enter="emit('refresh')" />
            <el-button type="primary" @click="emit('refresh')" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <el-button type="warning" @click="emit('refreshContracts')" :loading="refreshing">
              <el-icon><Download /></el-icon>
              强制同步
            </el-button>
          </el-space>
        </div>
      </template>

      <div class="table-wrapper">
        <el-table :data="contracts" stripe v-loading="loading" :size="isMobile ? 'small' : 'default'">
          <template #empty>
            <el-empty description="暂无合约信息" />
          </template>
          <el-table-column prop="symbol" label="合约代码" width="110">
            <template #default="{ row }">
              {{ row.symbol }}
              <el-tag v-if="row.is_main" type="danger" size="small" effect="dark" style="margin-left: 4px">主力</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" prop="name" label="合约名称" width="200" show-overflow-tooltip />
          <el-table-column prop="exchange_id" label="交易所" :width="isMobile ? 70 : 100">
            <template #default="{ row }">
              <el-tag size="small">{{ row.exchange_id }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="product_type" label="类型" :width="isMobile ? 60 : 80" />
          <el-table-column v-if="!isMobile" prop="volume_multiple" label="合约乘数" width="100" align="right" />
          <el-table-column v-if="!isMobile" prop="price_tick" label="最小变动价位" width="120" align="right">
            <template #default="{ row }">
              {{ formatNumber(row.price_tick) }}
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" prop="min_volume" label="最小手数" width="100" align="right" />
          <el-table-column v-if="!isMobile" prop="option_strike" label="行权价" width="100" align="right">
            <template #default="{ row }">
              {{ row.option_strike ? formatNumber(row.option_strike) : '-' }}
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" prop="option_underlying" label="标的合约" width="120">
            <template #default="{ row }">
              {{ row.option_underlying || '-' }}
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" prop="update_date" label="更新日期" />
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import type { ContractInfo, ExchangeInfo } from '@/types'

interface ContractFilter {
  exchange_id: string
  symbol_keyword: string
}

const props = defineProps<{
  loading: boolean
  contracts: ContractInfo[]
  exchanges: ExchangeInfo[]
  refreshing: boolean
  filter: ContractFilter
}>()

const emit = defineEmits<{
  refresh: []
  refreshContracts: []
  'update:filter': [filter: ContractFilter]
}>()

const localFilter = computed({
  get: () => props.filter,
  set: (val) => emit('update:filter', val)
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
