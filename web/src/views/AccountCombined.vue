<template>
  <div class="account-combined">
    <el-tabs v-model="activeTab" class="account-tabs">
      <!-- 账户详情 Tab -->
      <el-tab-pane label="账户详情" name="detail">
        <AccountDetailTab
          :loading="loading"
          @refresh="loadAccountData"
          @refresh-positions="loadPositionData"
          @close-position="handleClosePosition"
        />
      </el-tab-pane>

      <!-- 交易 Tab -->
      <el-tab-pane label="账户交易" name="trading">
        <AccountTradingTab
          :loading="loading"
          :quotes="quotes"
          :orders="store.currentOrders"
          v-model:order-tab="orderTab"
          @refresh-quotes="loadQuotes"
          @show-subscribe="showSubscribeDialog = true"
          @refresh-orders="loadOrderData"
          @show-order="showOrderInputDialog = true"
          @cancel-order="handleCancel"
          @order-selection-change="handleOrderSelectionChange"
        />
      </el-tab-pane>

      <!-- 成交记录 Tab -->
      <el-tab-pane label="成交记录" name="trade">
        <AccountTradeTab
          :loading="loading"
          :trades="store.currentTrades"
          v-model:date-filter="tradeDateFilter"
          @refresh="loadTradeData"
        />
      </el-tab-pane>

      <!-- 报单指令 Tab -->
      <el-tab-pane label="报单指令" name="order-cmd">
        <AccountOrderCmdTab
          :loading="loading"
          :order-cmds="orderCmds"
          v-model:status="orderCmdStatus"
          :cancelling-cmd-id="cancellingCmdId"
          @refresh="loadOrderCmdData"
          @cancel-order-cmd="handleCancelOrderCmd"
        />
      </el-tab-pane>

      <!-- 合约信息 Tab -->
      <el-tab-pane label="合约信息" name="contract">
        <AccountContractTab
          :loading="loading"
          :contracts="contracts"
          :exchanges="exchanges"
          :refreshing="refreshingContracts"
          v-model:filter="contractFilter"
          @refresh="loadContracts"
          @refresh-contracts="handleRefreshContracts"
        />
      </el-tab-pane>

      <!-- 设置 Tab -->
      <el-tab-pane label="账户设置" name="setting">
        <AccountSettingTab
          :loading-tasks="loadingTasks"
          :operating-job="operatingJob"
          :tasks="tasks"
          :updating="updatingRisk"
          v-model:risk-form="riskForm"
          @refresh-tasks="loadTasks"
          @operate-job="handleOperateJob"
          @update-risk-control="updateRiskControl"
        />
      </el-tab-pane>
    </el-tabs>

    <!-- 平仓对话框 -->
    <el-dialog v-model="showCloseDialog" title="确认平仓" width="90%" style="max-width: 500px">
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

    <!-- 报单对话框 -->
    <el-dialog v-model="showOrderInputDialog" title="报单" width="90%" style="max-width: 500px">
      <el-form :model="orderForm" label-width="100px">
        <el-form-item label="合约代码">
          <el-input v-model="orderForm.symbol" placeholder="如: rb2605" />
        </el-form-item>
        <el-form-item label="买卖方向">
          <el-radio-group v-model="orderForm.direction">
            <el-radio value="BUY">买入</el-radio>
            <el-radio value="SELL">卖出</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="开平标志">
          <el-radio-group v-model="orderForm.offset">
            <el-radio value="OPEN">开仓</el-radio>
            <el-radio value="CLOSE">平仓</el-radio>
            <el-radio value="CLOSETODAY">平今</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="手数">
          <el-input-number v-model="orderForm.volume" :min="1" :max="1000" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number v-model="orderForm.price" :min="0" :precision="2" placeholder="0表示市价" controls-position="right" style="width: 100%" />
          <span class="ml-2 text-sm text-gray-500">留空或0为市价</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showOrderInputDialog = false">取消</el-button>
        <el-button type="primary" @click="showOrderConfirmDialog = true">下一步</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showOrderConfirmDialog" title="确认报单" width="90%" style="max-width: 500px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="合约代码">
          {{ orderForm.symbol }}
        </el-descriptions-item>
        <el-descriptions-item label="买卖方向">
          <el-tag :type="orderForm.direction === 'BUY' ? 'success' : 'danger'">
            {{ orderForm.direction === 'BUY' ? '买入' : '卖出' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="开平标志">
          {{ orderForm.offset === 'OPEN' ? '开仓' : orderForm.offset === 'CLOSE' ? '平仓' : '平今' }}
        </el-descriptions-item>
        <el-descriptions-item label="手数">
          {{ orderForm.volume }} 手
        </el-descriptions-item>
        <el-descriptions-item label="价格">
          {{ (orderForm.price && orderForm.price > 0) ? formatNumber(orderForm.price) : '市价' }}
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="showOrderConfirmDialog = false">返回修改</el-button>
        <el-button type="primary" @click="handleCreateOrder" :loading="creating">
          确认报单
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCancelDialog" title="确认撤单" width="90%" style="max-width: 400px">
      <div style="margin-bottom: 15px;">
        <p><strong>委托单ID：</strong> {{ cancelForm.orderId }}</p>
        <p><strong>合约：</strong> {{ cancelForm.instrumentId }}</p>
        <p><strong>方向：</strong>
          <el-tag :type="cancelForm.direction === 'BUY' ? 'success' : 'danger'" size="small">
            {{ cancelForm.direction === 'BUY' ? '买入' : '卖出' }}
          </el-tag>
        </p>
        <p><strong>开平：</strong> {{ cancelForm.offset === 'OPEN' ? '开仓' : cancelForm.offset === 'CLOSE' ? '平仓' : '平今' }}</p>
        <p><strong>报单手数：</strong> {{ cancelForm.volume }} 手</p>
        <p><strong>价格：</strong>
          {{ cancelForm.price > 0 ? formatNumber(cancelForm.price) : '市价' }}
        </p>
      </div>
      <template #footer>
        <el-button @click="showCancelDialog = false">取消</el-button>
        <el-button type="danger" @click="handleCancelOrderConfirm" :loading="cancelling">
          确认撤单
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showSubscribeDialog" title="订阅行情" width="90%" style="max-width: 400px">
      <el-form :model="subscribeForm" label-width="100px">
        <el-form-item label="合约代码">
          <el-input v-model="subscribeForm.symbol" placeholder="如: rb2505" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSubscribeDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubscribe" :loading="subscribing">
          订阅
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useStore } from '@/stores'
import { positionApi, orderApi, quoteApi, orderCmdApi, contractApi, systemApi, jobsApi } from '@/api'
import wsManager from '@/ws'
import AccountDetailTab from './account/AccountDetailTab.vue'
import AccountTradingTab from './account/AccountTradingTab.vue'
import AccountTradeTab from './account/AccountTradeTab.vue'
import AccountOrderCmdTab from './account/AccountOrderCmdTab.vue'
import AccountContractTab from './account/AccountContractTab.vue'
import AccountSettingTab from './account/AccountSettingTab.vue'
import type { Position, ManualOrderRequest, Order, Quote, OrderCmd, ContractInfo, ExchangeInfo, Job } from '@/types'

const store = useStore()
const loading = ref(false)
const creating = ref(false)
const subscribing = ref(false)
const cancelling = ref(false)

// Tab 相关
const activeTab = ref('detail')
const orderTab = ref<'PENDING' | 'FINISHED' | 'ERROR'>('PENDING')

// 账户详情相关
const showCloseDialog = ref(false)
const closeForm = reactive({
  symbol: '',
  exchange_id: '',
  direction: 'BUY' as 'BUY' | 'SELL',
  offset: 'CLOSE',
  volume: 0,
  maxVolume: 0,
  price: 0
})

// 交易相关
const showOrderInputDialog = ref(false)
const showOrderConfirmDialog = ref(false)
const showCancelDialog = ref(false)
const showSubscribeDialog = ref(false)
const quotes = ref<Quote[]>([])
const selectedOrders = ref<Order[]>([])

// 成交记录相关
const tradeDateFilter = ref(new Date().toISOString().split('T')[0])

// 报单指令相关
const orderCmds = ref<OrderCmd[]>([])
const orderCmdStatus = ref<'active' | 'finished'>('active')
const cancellingCmdId = ref<string | null>(null)

// 合约信息相关
const contracts = ref<ContractInfo[]>([])
const exchanges = ref<ExchangeInfo[]>([])
const refreshingContracts = ref(false)
const contractFilter = reactive({
  exchange_id: '',
  symbol_keyword: ''
})

// 设置相关
const updatingRisk = ref(false)
const loadingTasks = ref(false)
const operatingJob = ref<string | null>(null)
const tasks = ref<Job[]>([])

const orderForm = reactive<ManualOrderRequest>({
  symbol: '',
  direction: 'BUY',
  offset: 'OPEN',
  volume: 1,
  price: null,
  account_id: store.selectedAccountId!
})

const cancelForm = reactive({
  orderId: '',
  instrumentId: '',
  direction: 'BUY' as 'BUY' | 'SELL',
  offset: 'OPEN',
  volume: 0,
  price: 0
})

const subscribeForm = reactive({
  symbol: ''
})

const statusMap: Record<string, string> = {
  'PENDING': 'ALIVE',
  'FINISHED': 'FINISHED',
  'ERROR': 'REJECTED'
}

const riskForm = reactive({
  max_daily_orders: 100,
  max_daily_cancels: 50,
  max_order_volume: 50,
  max_split_volume: 5,
  order_timeout: 5
})

// ========== 账户详情方法 ==========
async function loadAccountData() {
  loading.value = true
  try {
    await store.loadCurrentAccount()
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

  closeForm.symbol = position.symbol
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

// ========== 交易方法 ==========
async function loadOrderData() {
  loading.value = true
  try {
    const backendStatus = statusMap[orderTab.value] || 'ALIVE'
    await store.loadOrders(backendStatus, store.selectedAccountId || undefined)
  } finally {
    loading.value = false
  }
}

async function loadQuotes() {
  loading.value = true
  try {
    const result = await quoteApi.getSubscribedQuotes(store.selectedAccountId || undefined)
    quotes.value = result || []
  } catch (error: any) {
    ElMessage.error(`加载行情失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function handleTickUpdate(tickData: Quote) {
  if (!tickData || !tickData.symbol) return

  const index = quotes.value.findIndex(q => q.symbol === tickData.symbol)
  if (index !== -1) {
    quotes.value.splice(index, 1, {
      ...quotes.value[index],
      ...tickData
    })
  } else {
    quotes.value.push({ ...tickData })
  }
}

function handleOrderSelectionChange(selection: Order[]) {
  selectedOrders.value = selection
}

async function handleCreateOrder() {
  if (!orderForm.symbol || !orderForm.direction || !orderForm.offset || orderForm.volume <= 0) {
    ElMessage.warning('请填写完整的报单信息')
    return
  }
  if (!store.selectedAccountId) {
    ElMessage.error('请先选择账户')
    return
  }

  creating.value = true
  try {
    const orderData = {
      ...orderForm,
      account_id: store.selectedAccountId
    }
    const result = await orderApi.createOrder(orderData)
    ElMessage.success(`报单成功，委托单ID: ${result.order_id}`)
    showOrderConfirmDialog.value = false
    showOrderInputDialog.value = false
    orderForm.symbol = ''
    orderForm.direction = 'BUY'
    orderForm.offset = 'OPEN'
    orderForm.volume = 1
    orderForm.price = null
    await loadOrderData()
  } catch (error: any) {
    ElMessage.error(`报单失败: ${error.message}`)
  } finally {
    creating.value = false
  }
}

async function handleCancel(orderId: string) {
  const order = store.currentOrders.find(o => o.order_id === orderId)
  if (!order) return

  cancelForm.orderId = orderId
  cancelForm.instrumentId = order.symbol
  cancelForm.direction = order.direction as 'BUY' | 'SELL'
  cancelForm.offset = order.offset
  cancelForm.volume = order.volume_orign
  cancelForm.price = order.limit_price || 0

  showCancelDialog.value = true
}

async function handleCancelOrderConfirm() {
  try {
    await orderApi.cancelOrder(cancelForm.orderId, store.selectedAccountId || undefined)
    ElMessage.success('撤单成功')
    showCancelDialog.value = false
    await loadOrderData()
  } catch (error: any) {
    ElMessage.error(`撤单失败: ${error.message}`)
    showCancelDialog.value = false
  }
}

async function handleSubscribe() {
  if (!subscribeForm.symbol) {
    ElMessage.warning('请输入合约代码')
    return
  }

  subscribing.value = true
  try {
    await quoteApi.subscribeSymbol(subscribeForm.symbol, store.selectedAccountId || undefined)
    ElMessage.success(`已订阅 ${subscribeForm.symbol}`)
    showSubscribeDialog.value = false
    subscribeForm.symbol = ''
    await loadQuotes()
  } catch (error: any) {
    ElMessage.error(`订阅失败: ${error.message}`)
  } finally {
    subscribing.value = false
  }
}

// ========== 成交记录方法 ==========
async function loadTradeData() {
  loading.value = true
  try {
    await store.loadTrades(tradeDateFilter.value, store.selectedAccountId || undefined)
  } finally {
    loading.value = false
  }
}

// ========== 报单指令方法 ==========
async function loadOrderCmdData() {
  loading.value = true
  try {
    const result = await orderCmdApi.getOrderCmdsStatus(store.selectedAccountId || undefined, orderCmdStatus.value)
    orderCmds.value = result || []
  } catch (error: any) {
    ElMessage.error(`加载报单指令失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function handleCancelOrderCmd(cmdId: string) {
  try {
    await ElMessageBox.confirm(
      `确定要强制取消报单指令 ${cmdId} 吗？`,
      '确认取消',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }

  cancellingCmdId.value = cmdId
  try {
    await orderCmdApi.cancelOrderCmd(cmdId, store.selectedAccountId || undefined)
    ElMessage.success('取消指令成功')
    await loadOrderCmdData()
  } catch (error: any) {
    ElMessage.error(`取消指令失败: ${error.message}`)
  } finally {
    cancellingCmdId.value = null
  }
}

// ========== 合约信息方法 ==========
async function loadContracts() {
  loading.value = true
  try {
    const params = {
      ...(contractFilter.exchange_id ? { exchange_id: contractFilter.exchange_id } : {}),
      ...(contractFilter.symbol_keyword ? { symbol_keyword: contractFilter.symbol_keyword } : {})
    }
    contracts.value = await contractApi.getContracts(params)
    if (exchanges.value.length === 0) {
      loadExchanges()
    }
  } catch (error: any) {
    ElMessage.error(`加载合约信息失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function loadExchanges() {
  try {
    exchanges.value = await contractApi.getExchanges()
  } catch (error: any) {
    console.error(`加载交易所列表失败: ${error.message}`)
  }
}

async function handleRefreshContracts() {
  refreshingContracts.value = true
  try {
    const result = await contractApi.refreshContracts(store.selectedAccountId || undefined)
    if (result.success) {
      ElMessage.success('合约信息刷新成功')
      await loadContracts()
    } else {
      const results = result.results || {}
      const successCount = Object.values(results).filter((r: any) => r.success).length
      const totalCount = Object.keys(results).length

      if (successCount > 0) {
        ElMessage.warning(`部分账户刷新成功 (${successCount}/${totalCount})`)
        await loadContracts()
      } else {
        ElMessage.error('合约信息刷新失败，请检查账户连接状态')
      }
    }
  } catch (error: any) {
    ElMessage.error(`刷新合约信息失败: ${error.message}`)
  } finally {
    refreshingContracts.value = false
  }
}

// ========== 设置方法 ==========
async function updateRiskControl() {
  updatingRisk.value = true
  try {
    await systemApi.updateRiskControl(
      riskForm.max_daily_orders,
      riskForm.max_daily_cancels,
      riskForm.max_order_volume,
      riskForm.max_split_volume,
      riskForm.order_timeout,
      store.selectedAccountId || undefined
    )
    ElMessage.success('风控参数已更新')
    await store.loadAllAccounts()
  } catch (error: any) {
    console.error('更新风控参数失败:', error)
    ElMessage.error(`更新风控参数失败: ${error.message}`)
  } finally {
    updatingRisk.value = false
  }
}

async function loadTasks() {
  loadingTasks.value = true
  try {
    const accountId = store.selectedAccountId || undefined
    const result = await systemApi.getScheduledTasks(accountId)
    tasks.value = result.tasks
  } catch (error: any) {
    ElMessage.error(`加载定时任务失败: ${error.message}`)
  } finally {
    loadingTasks.value = false
  }
}

async function handleOperateJob(row: Job, action: 'pause' | 'resume' | 'trigger') {
  const accountId = store.selectedAccountId
  if (!accountId) {
    ElMessage.error('请先选择账户')
    return
  }
  const actionKey = `${row.job_id}_${action}`
  operatingJob.value = actionKey
  try {
    await jobsApi.operateJob(row.job_id, action, accountId)
    const actionText = action === 'pause' ? '暂停' : action === 'resume' ? '恢复' : '触发'
    ElMessage.success(`任务 ${row.job_name} 已${actionText}`)
    if (action === 'pause') {
      row.enabled = false
    } else if (action === 'resume') {
      row.enabled = true
    }
    await loadTasks()
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  } finally {
    operatingJob.value = null
  }
}

// ========== 工具函数 ==========
function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '0.00'
  return num.toFixed(2)
}

// ========== 监听 ==========
watch(activeTab, (newTab, oldTab) => {
  if (newTab === 'detail') {
    loadAccountData()
    loadPositionData()
  } else if (newTab === 'trading') {
    loadQuotes()
    loadOrderData()
    wsManager.subscribeQuotes()
  } else if (newTab === 'trade') {
    loadTradeData()
  } else if (newTab === 'order-cmd') {
    loadOrderCmdData()
  } else if (newTab === 'contract') {
    loadContracts()
  } else if (newTab === 'setting') {
    loadTasks()
  }

  if (oldTab === 'trading') {
    wsManager.unsubscribeQuotes()
  }
})

watch(() => store.selectedAccountId, (newId) => {
  if (newId) {
    if (activeTab.value === 'detail') {
      loadAccountData()
      loadPositionData()
    } else if (activeTab.value === 'trading') {
      loadQuotes()
      loadOrderData()
    } else if (activeTab.value === 'trade') {
      loadTradeData()
    } else if (activeTab.value === 'order-cmd') {
      loadOrderCmdData()
    } else if (activeTab.value === 'contract') {
      loadContracts()
    } else if (activeTab.value === 'setting') {
      loadTasks()
    }
  }
})

onMounted(async () => {
  // 初始加载
  if (activeTab.value === 'detail') {
    await loadAccountData()
    await loadPositionData()
  } else if (activeTab.value === 'trading') {
    await loadQuotes()
    await loadOrderData()
    wsManager.subscribeQuotes()
  } else if (activeTab.value === 'trade') {
    await loadTradeData()
  } else if (activeTab.value === 'order-cmd') {
    await loadOrderCmdData()
  } else if (activeTab.value === 'contract') {
    await loadContracts()
  } else if (activeTab.value === 'setting') {
    await loadTasks()
  }

  wsManager.onTickUpdate(handleTickUpdate)
})

onUnmounted(() => {
  wsManager.onTickUpdate(handleTickUpdate)()
  wsManager.unsubscribeQuotes()
})
</script>

<style scoped>
.account-combined {
  padding: 0;
  width: 100%;
}

.account-tabs {
  width: 100%;
}

.account-tabs :deep(.el-tabs__content) {
  overflow-x: auto;
}
</style>
