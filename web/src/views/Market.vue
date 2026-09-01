<template>
  <div class="market-page">
    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- 合约 -->
        <el-tab-pane label="合约" name="contracts">
          <el-form :inline="true">
            <el-form-item label="合约">
              <el-input
                v-model="contractKeyword"
                placeholder="合约代码/名称"
                style="width: 160px"
                clearable
                @keyup.enter="loadContracts"
              />
            </el-form-item>
            <el-form-item label="交易所">
              <el-select v-model="contractExchange" style="width: 120px" clearable>
                <el-option
                  v-for="ex in exchanges"
                  :key="ex.exchange_id"
                  :label="ex.exchange_id"
                  :value="ex.exchange_id"
                />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="contractsLoading" @click="loadContracts">
                查询
              </el-button>
              <el-button :loading="refreshing" @click="handleRefreshContracts">刷新合约</el-button>
            </el-form-item>
          </el-form>

          <el-table
            :data="contracts"
            v-loading="contractsLoading"
            stripe
            size="small"
            max-height="560"
          >
            <el-table-column prop="symbol" label="合约代码" width="120" sortable />
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="exchange_id" label="交易所" width="90" />
            <el-table-column prop="volume_multiple" label="乘数" width="70" align="right" />
            <el-table-column prop="price_tick" label="最小变动" width="90" align="right" />
            <el-table-column prop="min_volume" label="最小手数" width="90" align="right" />
            <el-table-column prop="option_type" label="期权类型" width="90">
              <template #default="{ row }">{{ row.option_type || '-' }}</template>
            </el-table-column>
            <el-table-column prop="update_date" label="更新日期" width="100" />
          </el-table>
          <div class="tab-footer">共 {{ contracts.length }} 个合约</div>
        </el-tab-pane>

        <!-- Tick（v-if 切走时卸载，避免高频行情驱动隐藏表格持续重渲染） -->
        <el-tab-pane label="Tick" name="tick">
          <template v-if="activeTab === 'tick'">
            <el-table :data="quoteList" stripe size="small" max-height="560" v-loading="false">
              <el-table-column prop="symbol" label="合约代码" width="120" sortable />
              <el-table-column label="最新价" align="right" width="110">
                <template #default="{ row }">{{ formatPrice(row.last_price) }}</template>
              </el-table-column>
              <el-table-column label="买一价" align="right" width="110">
                <template #default="{ row }">{{ formatPrice(row.bid_price1) }}</template>
              </el-table-column>
              <el-table-column label="卖一价" align="right" width="110">
                <template #default="{ row }">{{ formatPrice(row.ask_price1) }}</template>
              </el-table-column>
              <el-table-column prop="volume" label="成交量" align="right" width="110" />
              <el-table-column prop="datetime" label="时间" min-width="170">
                <template #default="{ row }">{{ formatTime(row.datetime) }}</template>
              </el-table-column>
            </el-table>
            <div class="tab-footer">共 {{ quoteList.length }} 个合约行情（WebSocket 实时推送）</div>
          </template>
        </el-tab-pane>

        <!-- K线 -->
        <el-tab-pane label="K线" name="bars" lazy>
          <Bars />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { contractApi } from '@/api/contract'
import { useStore } from '@/stores'
import type { ContractInfo, ExchangeInfo } from '@/types'
import Bars from './Bars.vue'

const store = useStore()

const activeTab = ref('contracts')

// ==================== 合约 ====================
const contracts = ref<ContractInfo[]>([])
const exchanges = ref<ExchangeInfo[]>([])
const contractKeyword = ref('')
const contractExchange = ref('')
const contractsLoading = ref(false)
const refreshing = ref(false)

async function loadContracts() {
  contractsLoading.value = true
  try {
    contracts.value = await contractApi.getContracts({
      symbol_keyword: contractKeyword.value || undefined,
      exchange_id: contractExchange.value || undefined,
    })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '查询合约失败')
  } finally {
    contractsLoading.value = false
  }
}

async function handleRefreshContracts() {
  refreshing.value = true
  try {
    const result = await contractApi.refreshContracts()
    const okCount = Object.values(result.results || {}).filter((r) => r.success).length
    ElMessage.success(`合约刷新完成: ${okCount} 个账户成功`)
    await loadContracts()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '刷新合约失败')
  } finally {
    refreshing.value = false
  }
}

// ==================== Tick ====================
const quoteList = computed(() => {
  return Array.from(store.quotes.values()).sort((a, b) =>
    String(a.symbol).localeCompare(String(b.symbol)),
  )
})

function formatPrice(price: number | null): string {
  return price === null || price === undefined ? '-' : String(price)
}

function formatTime(dt: string): string {
  if (!dt) return '-'
  return dt.length > 19 ? dt.slice(0, 19) : dt
}

onMounted(async () => {
  loadContracts()
  try {
    exchanges.value = await contractApi.getExchanges()
  } catch {
    exchanges.value = []
  }
})
</script>

<style scoped>
.market-page {
  padding: 16px;
}

.tab-footer {
  margin-top: 8px;
  color: #909399;
  font-size: 12px;
}
</style>
