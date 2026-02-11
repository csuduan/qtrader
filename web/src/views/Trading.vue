<template>
  <div class="trading-tabs">
    <el-tabs v-model="activeTab" class="trading-tabs-inner">
      <el-tab-pane label="账户交易" name="trading">
        <el-row :gutter="20" style="display: flex; flex-wrap: nowrap;">
          <el-col :span="6" style="flex: 0 0 auto; min-width: 350px;">
            <el-card shadow="hover">
              <template #header>
                <div class="card-header">
                  <span>行情订阅</span>
                  <el-space>
                    <el-button @click="loadQuotes" :loading="loading">
                      <el-icon><Refresh /></el-icon>
                      刷新
                    </el-button>
                    <el-button type="primary" @click="showSubscribeDialog = true">
                      <el-icon><Plus /></el-icon>
                      订阅
                    </el-button>
                  </el-space>
                </div>
              </template>

              <el-table
                :data="quotes"
                stripe
                v-loading="loading"
                table-layout="fixed"
                height="calc(100vh - 320px)"
              >
                <template #empty>
                  <el-empty description="暂无订阅行情" />
                </template>
                <el-table-column prop="symbol" label="合约" width="80" >
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
                <el-table-column prop="datetime" label="时间" width="85">
                  <template #default="{ row }">
                    {{ formatTime(row.datetime) }}
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>

          <el-col :span="18" style="flex: 1; min-width: 0;">
            <el-card shadow="hover">
              <template #header>
                <div class="card-header">
                  <el-tabs v-model="orderTab" type="card">
                    <el-tab-pane label="挂单" name="PENDING" />
                    <el-tab-pane label="已成交" name="FINISHED" />
                    <el-tab-pane label="废单" name="ERROR" />
                  </el-tabs>
                  <el-space>
                    <el-button type="primary" @click="showOrderInputDialog = true">
                      <el-icon><Plus /></el-icon>
                      报单
                    </el-button>
                    <el-button @click="loadOrderData" :loading="loading">
                      <el-icon><Refresh /></el-icon>
                      刷新
                    </el-button>
                  </el-space>
                </div>
              </template>

              <el-table
                :data="store.currentOrders"
                stripe
                v-loading="loading"
                height="calc(100vh - 380px)"
                table-layout="fixed"
                @selection-change="handleOrderSelectionChange"
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
                  v-if="orderTab === 'PENDING'"
                  label="操作"
                  width="100"
                  fixed="right"
                >
                  <template #default="{ row }">
                    <el-button
                      type="danger"
                      size="small"
                      @click="handleCancel(row.order_id)"
                    >
                      撤单
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="成交记录" name="trade">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>成交记录</span>
              <el-space>
                <el-date-picker
                  v-model="tradeDateFilter"
                  type="date"
                  placeholder="选择日期"
                  format="YYYY-MM-DD"
                  value-format="YYYY-MM-DD"
                  clearable
                />
                <el-button type="primary" @click="loadTradeData" :loading="loading">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
              </el-space>
            </div>
          </template>

          <el-table :data="sortedTrades" stripe v-loading="loading" height="400">
            <template #empty>
              <el-empty description="暂无成交记录" />
            </template>
            <el-table-column prop="trade_id" label="成交ID" width="180" show-overflow-tooltip />
            <el-table-column prop="symbol" label="合约" width="120" />
            <el-table-column prop="direction" label="方向" width="80">
              <template #default="{ row }">
                <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small">
                  {{ row.direction === 'BUY' ? '买' : '卖' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="offset" label="开平" width="80" />
            <el-table-column prop="price" label="成交价" width="100">
              <template #default="{ row }">
                {{ formatNumber(row.price) }}
              </template>
            </el-table-column>
            <el-table-column prop="volume" label="手数" width="80" />
            <el-table-column prop="order_id" label="委托单ID" width="180" show-overflow-tooltip />
            <el-table-column prop="created_at" label="成交时间">
              <template #default="{ row }">
                {{ formatDateTime(row.trade_date_time) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="报单指令" name="order-cmd">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>报单指令</span>
              <el-space>
                <el-radio-group v-model="orderCmdStatus" >
                  <el-radio-button label="active">未完成</el-radio-button>
                  <el-radio-button label="finished">已完成</el-radio-button>
                </el-radio-group>
                <el-button type="primary" @click="loadOrderCmdData" :loading="loading">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
              </el-space>
            </div>
          </template>

          <el-table :data="sortedOrderCmds" stripe v-loading="loading" height="400">
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
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="合约信息" name="contract">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>合约信息</span>
              <el-space>
                <el-select v-model="contractFilter.exchange_id" placeholder="交易所" clearable style="width: 120px" @change="loadContracts">
                  <el-option label="全部" value="" />
                  <el-option v-for="ex in exchanges" :key="ex.exchange_id" :label="`${ex.exchange_id} (${ex.contract_count})`" :value="ex.exchange_id" />
                </el-select>
                <el-input v-model="contractFilter.symbol_keyword" placeholder="合约代码" clearable style="width: 150px" @keyup.enter="loadContracts" />
                <el-button type="primary" @click="loadContracts" :loading="loading">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
              </el-space>
            </div>
          </template>

          <el-table :data="contracts" stripe v-loading="loading" height="calc(100vh - 280px)">
            <template #empty>
              <el-empty description="暂无合约信息" />
            </template>
            <el-table-column prop="symbol" label="合约代码" width="120" fixed />
            <el-table-column prop="name" label="合约名称" width="200" show-overflow-tooltip />
            <el-table-column prop="exchange_id" label="交易所" width="100">
              <template #default="{ row }">
                <el-tag size="small">{{ row.exchange_id }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="product_type" label="类型" width="80" />
            <el-table-column prop="volume_multiple" label="合约乘数" width="100" align="right" />
            <el-table-column prop="price_tick" label="最小变动价位" width="120" align="right">
              <template #default="{ row }">
                {{ formatNumber(row.price_tick) }}
              </template>
            </el-table-column>
            <el-table-column prop="min_volume" label="最小手数" width="100" align="right" />
            <el-table-column prop="option_strike" label="行权价" width="100" align="right">
              <template #default="{ row }">
                {{ row.option_strike ? formatNumber(row.option_strike) : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="option_underlying" label="标的合约" width="120">
              <template #default="{ row }">
                {{ row.option_underlying || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="update_date" label="更新日期" width="110" />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showOrderInputDialog" title="报单" width="500px">
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

    <el-dialog v-model="showOrderConfirmDialog" title="确认报单" width="500px">
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

    <el-dialog v-model="showCancelDialog" title="确认撤单" width="400px">
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

    <el-dialog v-model="showSubscribeDialog" title="订阅行情" width="400px">
      <el-form :model="subscribeForm" label-width="100px">
        <el-form-item label="合约代码">
          <el-input v-model="subscribeForm.symbol" placeholder="如: SHFE.rb2505 或 rb2505" />
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
import { ref, reactive, watch, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { orderApi, quoteApi, orderCmdApi, contractApi } from '@/api'
import wsManager from '@/ws'
import type { ManualOrderRequest, Order, Quote, OrderCmd, ContractInfo, ExchangeInfo } from '@/types'

const store = useStore()
const loading = ref(false)
const loadingQuotes = ref(false)
const creating = ref(false)
const subscribing = ref(false)
const cancelling = ref(false)
const showOrderInputDialog = ref(false)
const showOrderConfirmDialog = ref(false)
const showCancelDialog = ref(false)
const showSubscribeDialog = ref(false)
const activeTab = ref('trading')
const orderTab = ref('PENDING')

const selectedOrders = ref<Order[]>([])
const quotes = ref<Quote[]>([])
const tradeDateFilter = ref(new Date().toISOString().split('T')[0])
const orderCmds = ref<OrderCmd[]>([])
const orderCmdStatus = ref<'active' | 'finished'>('active')

// 合约信息相关
const contracts = ref<ContractInfo[]>([])
const exchanges = ref<ExchangeInfo[]>([])
const contractFilter = reactive({
  exchange_id: '',
  product_type: '',
  symbol_keyword: ''
})

const statusMap: Record<string, string> = {
  'PENDING': 'ALIVE',
  'FINISHED': 'FINISHED',
  'ERROR': 'REJECTED'
}

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
  direction: 'BUY',
  offset: 'OPEN',
  volume: 0,
  price: 0
})

const subscribeForm = reactive({
  symbol: ''
})

// 按时间倒序排序的成交记录
const sortedTrades = computed(() => {
  if (!store.currentTrades || store.currentTrades.length === 0) return []
  return [...store.currentTrades].sort((a, b) => {
    // trade_date_time 可能是数字（Unix时间戳秒）或字符串（ISO格式）
    let timeA = 0
    let timeB = 0
    if (typeof a.trade_date_time === 'number') {
      timeA = a.trade_date_time
    } else if (typeof a.trade_date_time === 'string') {
      timeA = new Date(a.trade_date_time).getTime() / 1000
    }
    if (typeof b.trade_date_time === 'number') {
      timeB = b.trade_date_time
    } else if (typeof b.trade_date_time === 'string') {
      timeB = new Date(b.trade_date_time).getTime() / 1000
    }
    return timeB - timeA
  })
})

// 按开始时间倒序排序的报单指令
const sortedOrderCmds = computed(() => {
  if (!orderCmds.value || orderCmds.value.length === 0) return []
  return [...orderCmds.value].sort((a, b) => {
    const timeA = a.started_at ? new Date(a.started_at).getTime() : 0
    const timeB = b.started_at ? new Date(b.started_at).getTime() : 0
    return timeB - timeA
  })
})

function handleTickUpdate(tickData: Quote) {
  if (!tickData || !tickData.symbol) return

  const index = quotes.value.findIndex(q => q.symbol === tickData.symbol)
  if (index !== -1) {
    // 使用 splice 触发响应式更新
    quotes.value.splice(index, 1, {
      ...quotes.value[index],
      ...tickData
    })
  } else {
    quotes.value.push({
      ...tickData
    })
  }
}

async function loadOrderData() {
  loading.value = true
  try {
    const backendStatus = statusMap[orderTab.value]
    await store.loadOrders(backendStatus, store.selectedAccountId || undefined)
  } finally {
    loading.value = false
  }
}

async function loadTradeData() {
  loading.value = true
  try {
    await store.loadTrades(tradeDateFilter.value, store.selectedAccountId || undefined)
  } finally {
    loading.value = false
  }
}

async function loadQuotes() {
  loadingQuotes.value = true
  try {
    const result = await quoteApi.getSubscribedQuotes(store.selectedAccountId || undefined)
    quotes.value = result || []
  } catch (error: any) {
    ElMessage.error(`加载行情失败: ${error.message}`)
  } finally {
    loadingQuotes.value = false
  }
}

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

async function loadContracts() {
  loading.value = true
  try {
    const params = {
      ...(contractFilter.exchange_id ? { exchange_id: contractFilter.exchange_id } : {}),
      ...(contractFilter.symbol_keyword ? { symbol_keyword: contractFilter.symbol_keyword } : {})
    }
    contracts.value = await contractApi.getContracts(params)
    // 如果是第一次加载且没有选择交易所，同时加载交易所列表
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
  cancelForm.direction = order.direction
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

watch(activeTab, (newTab) => {
  if (newTab === 'trading') {
    loadQuotes()
    loadOrderData()
  } else if (newTab === 'trade') {
    loadTradeData()
  } else if (newTab === 'order-cmd') {
    loadOrderCmdData()
  } else if (newTab === 'contract') {
    loadContracts()
  }
})

watch(tradeDateFilter, () => {
  if (activeTab.value === 'trade') {
    loadTradeData()
  }
})

watch(orderTab, () => {
  if (activeTab.value === 'trading') {
    loadOrderData()
  }
})

watch(orderCmdStatus, () => {
  if (activeTab.value === 'order-cmd') {
    loadOrderCmdData()
  }
})

onMounted(async () => {
  if (activeTab.value === 'trading') {
    loadQuotes()
    loadOrderData()
  } else if (activeTab.value === 'trade') {
    loadTradeData()
  } else if (activeTab.value === 'order-cmd') {
    loadOrderCmdData()
  } else if (activeTab.value === 'contract') {
    loadContracts()
  }

  wsManager.onTickUpdate(handleTickUpdate)
})

onUnmounted(() => {
  wsManager.onTickUpdate(handleTickUpdate)()
})
</script>

<style scoped>
.trading-tabs {
  padding: 0;
  width: 100%;
}

.trading-tabs-inner {
  width: 100%;
}

.trading-tabs-inner .el-tabs__content {
  overflow-x: auto;
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
