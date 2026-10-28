<template>
  <div class="account-combined">
    <el-tabs v-model="activeTab" class="account-tabs">
      <!-- 账户详情 Tab -->
      <el-tab-pane label="账户详情" name="detail" lazy>
        <AccountDetailTab
          :loading="loading"
          @refresh="loadAccountData"
          @refresh-positions="loadPositionData"
          @close-positions="handleClosePositions"
        />
      </el-tab-pane>

      <!-- 交易 Tab -->
      <el-tab-pane label="账户交易" name="trading" lazy>
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
      <el-tab-pane label="成交记录" name="trade" lazy>
        <AccountTradeTab
          :loading="loading"
          :trades="store.currentTrades"
          v-model:date-filter="tradeDateFilter"
          @refresh="loadTradeData"
        />
      </el-tab-pane>

      <!-- 报单指令 Tab -->
      <el-tab-pane label="报单指令" name="order-cmd" lazy>
        <AccountOrderCmdTab
          :loading="loading"
          :order-cmds="orderCmds"
          v-model:status="orderCmdStatus"
          :cancelling-cmd-id="cancellingCmdId"
          @refresh="loadOrderCmdData"
          @cancel-order-cmd="handleCancelOrderCmd"
          @create-order-cmd="handleCreateOrderCmd"
        />
      </el-tab-pane>

      <!-- 设置 Tab -->
      <el-tab-pane label="账户设置" name="setting" lazy>
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

    <!-- 平仓对话框（走报单指令，自动拆分今昨仓） -->
    <el-dialog v-model="showCloseDialog" title="平仓" width="90%" style="max-width: 700px">
      <el-table :data="closeRows" size="small" border>
        <el-table-column prop="symbol" label="合约" min-width="90" />
        <el-table-column label="多头(今/昨)" width="100">
          <template #default="{ row }">
            <span class="long">{{ row.pos_long_td || 0 }} / {{ row.pos_long - (row.pos_long_td || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="空头(今/昨)" width="100">
          <template #default="{ row }">
            <span class="short">{{ row.pos_short_td || 0 }} / {{ row.pos_short - (row.pos_short_td || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="平仓手数" width="140">
          <template #default="{ row }">
            <el-input-number
              v-model="row.volume"
              :min="1"
              :max="Math.max(row.pos_long, row.pos_short)"
              size="small"
              controls-position="right"
              style="width: 120px"
            />
          </template>
        </el-table-column>
        <el-table-column label="价格" width="150">
          <template #default="{ row }">
            <el-input-number
              v-model="row.price"
              :min="0"
              :precision="2"
              size="small"
              controls-position="right"
              placeholder="0表示市价"
              style="width: 130px"
            />
          </template>
        </el-table-column>
      </el-table>
      <div class="text-sm text-gray-500" style="margin-top: 8px">
        价格留空或0为市价；平多/平空通过报单指令执行，自动按今昨仓拆分
      </div>
      <template #footer>
        <el-button @click="showCloseDialog = false">取消</el-button>
        <el-button type="danger" @click="handleClosePositionConfirm('SELL')" :loading="closing">
          平多
        </el-button>
        <el-button type="primary" @click="handleClosePositionConfirm('BUY')" :loading="closing">
          平空
        </el-button>
      </template>
    </el-dialog>

    <!-- 报单对话框 -->
    <el-dialog v-model="showOrderInputDialog" title="报单" width="90%" style="max-width: 500px">
      <el-form :model="orderForm" label-width="100px">
        <el-form-item label="合约代码">
          <el-input v-model="orderForm.symbol" :placeholder="symbolPlaceholder" />
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
          <el-input v-model="subscribeForm.symbol" :placeholder="symbolPlaceholder" />
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
import { orderApi, quoteApi, orderCmdApi, systemApi, jobsApi } from '@/api'
import wsManager from '@/ws'
import AccountDetailTab from './account/AccountDetailTab.vue'
import AccountTradingTab from './account/AccountTradingTab.vue'
import AccountTradeTab from './account/AccountTradeTab.vue'
import AccountOrderCmdTab from './account/AccountOrderCmdTab.vue'
import AccountSettingTab from './account/AccountSettingTab.vue'
import type { Position, ManualOrderRequest, Order, Quote, OrderCmd, Job } from '@/types'

const store = useStore()
const loading = ref(false)
const creating = ref(false)
const subscribing = ref(false)
const cancelling = ref(false)

// 合约输入框占位提示：后端最新螺纹钢主力（如 rb2701）
const symbolPlaceholder = ref('如: rb2605')
onMounted(() => {
  store.loadMainSymbol().then((s) => {
    if (s) symbolPlaceholder.value = `如: ${s}`
  })
})

// Tab 相关
const activeTab = ref('detail')
const orderTab = ref<'PENDING' | 'FINISHED' | 'ERROR'>('PENDING')

// 账户详情相关
const showCloseDialog = ref(false)
const closing = ref(false)
interface CloseRow {
  symbol: string
  pos_long: number
  pos_short: number
  pos_long_td: number
  pos_short_td: number
  volume: number
  price: number
}
const closeRows = ref<CloseRow[]>([])

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

function handleClosePositions(positions: Position[]) {
  if (positions.length === 0) return

  closeRows.value = positions.map(p => ({
    symbol: p.symbol ?? '',
    pos_long: p.pos_long,
    pos_short: p.pos_short,
    pos_long_td: p.pos_long_td || 0,
    pos_short_td: p.pos_short_td || 0,
    volume: Math.max(p.pos_long, p.pos_short),
    price: 0
  }))

  showCloseDialog.value = true
}

async function handleClosePositionConfirm(direction: 'BUY' | 'SELL') {
  if (!store.selectedAccountId) {
    ElMessage.error('请先选择账户')
    return
  }

  // 平多发SELL，平空发BUY；手数按对应方向的持仓封顶
  const side = direction === 'SELL' ? 'long' : 'short'
  const valid = closeRows.value
    .map(row => ({
      ...row,
      volume: Math.min(row.volume, side === 'long' ? row.pos_long : row.pos_short)
    }))
    .filter(row => (side === 'long' ? row.pos_long : row.pos_short) > 0 && row.volume > 0)
  if (valid.length === 0) {
    ElMessage.warning(side === 'long' ? '没有可平的多头持仓' : '没有可平的空头持仓')
    return
  }

  closing.value = true
  const failed: string[] = []
  try {
    for (const row of valid) {
      try {
        await orderCmdApi.sendOrderCmd(
          {
            symbol: row.symbol,
            direction,
            offset: 'CLOSE',
            volume: row.volume,
            price: row.price || 0,
            source: '手动平仓'
          },
          store.selectedAccountId
        )
      } catch (error: any) {
        failed.push(`${row.symbol}: ${error.message}`)
      }
    }

    if (failed.length > 0) {
      ElMessage.error(`部分平仓指令发送失败: ${failed.join('; ')}`)
    } else {
      ElMessage.success(`平仓指令已发送 (${valid.length} 个合约)`)
      showCloseDialog.value = false
    }
  } finally {
    closing.value = false
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

/** 新增报单指令（账户级 OrderCmd，自动拆单/追价） */
async function handleCreateOrderCmd(form: {
  symbol: string
  direction: 'BUY' | 'SELL'
  offset: string
  volume: number
  price: number
}) {
  if (!store.selectedAccountId) {
    ElMessage.error('请先选择账户')
    return
  }
  try {
    const result = await orderCmdApi.sendOrderCmd(
      { ...form, source: '手动报单' },
      store.selectedAccountId
    )
    ElMessage.success(`报单指令已发送: ${form.symbol} ${form.volume}手（指令ID: ${result.cmd_id.slice(0, 8)}...）`)
    // 新指令为进行中，切回未完成页签并刷新
    if (orderCmdStatus.value !== 'active') {
      orderCmdStatus.value = 'active'
    }
    await loadOrderCmdData()
  } catch (error: any) {
    ElMessage.error(`发送报单指令失败: ${error.message}`)
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
  } else if (activeTab.value === 'setting') {
    await loadTasks()
  }

  unsubscribeTick = wsManager.onTickUpdate(handleTickUpdate)
})

// 保存取消函数，卸载时正确移除该回调（旧写法"再注册一次再调用"会残留一个订阅导致泄漏）
let unsubscribeTick: (() => void) | null = null

onUnmounted(() => {
  unsubscribeTick?.()
  unsubscribeTick = null
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

.long {
  color: #67c23a;
  font-weight: 600;
}

.short {
  color: #f56c6c;
  font-weight: 600;
}
</style>
