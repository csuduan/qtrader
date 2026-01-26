<template>
  <div class="account-tabs">
    <el-tabs v-model="activeTab" class="account-tabs-inner">
      <el-tab-pane label="账户信息" name="account">
        <el-card shadow="hover" v-if="store.account">
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
            <el-descriptions-item label="账户ID">{{ store.account.user_id || '-'}}</el-descriptions-item>
            <el-descriptions-item label="券商">{{ store.account.broker_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="币种">{{ store.account.currency }}</el-descriptions-item>
            <el-descriptions-item label="风险率">
              <el-tag :type="store.account.risk_ratio > 1 ? 'danger' : 'success'">
                {{ formatNumber(store.account.risk_ratio) }}%
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="总资产" :span="2">
              <span class="balance">¥{{ formatNumber(store.account.balance) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="可用资金">
              <span class="available">¥{{ formatNumber(store.account.available) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="保证金占用">
              ¥{{ formatNumber(store.account.margin) }}
            </el-descriptions-item>
            <el-descriptions-item label="浮动盈亏">
              <span :class="store.account.float_profit >= 0 ? 'profit' : 'loss'">
                ¥{{ formatNumber(store.account.float_profit) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="持仓盈亏">
              <span :class="store.account.position_profit >= 0 ? 'profit' : 'loss'">
                ¥{{ formatNumber(store.account.position_profit) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="平仓盈亏">
              <span :class="store.account.close_profit >= 0 ? 'profit' : 'loss'">
                ¥{{ formatNumber(store.account.close_profit) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="更新时间">{{ formatDateTime(store.account.updated_at) }}</el-descriptions-item>
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
            :data="store.positions"
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

          <el-empty v-if="store.positions.length === 0" description="暂无持仓" />
        </el-card>
      </el-tab-pane>

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
                <el-table-column prop="symbol" label="合约" width="80" >
                   <template #default="{ row }">
                    {{ row.symbol.split('.')[1] }}
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
                <el-table-column prop="datetime" label="时间" width="80">
                  <template #default="{ row }">
                    {{ formatTime(row.datetime) }}
                  </template>
                </el-table-column>
              </el-table>

              <el-empty v-if="quotes.length === 0" description="暂无订阅行情" />
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
                :data="store.orders"
                stripe
                v-loading="loading"
                height="calc(100vh - 380px)"
                table-layout="fixed"
                @selection-change="handleOrderSelectionChange"
              >
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

              <el-empty v-if="store.orders.length === 0" description="暂无委托单" />
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

          <el-table :data="filteredTrades" stripe v-loading="loading" height="400">
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

          <el-empty v-if="store.trades.length === 0" description="暂无成交记录" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="策略" name="strategy">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>策略管理</span>
              <el-space>
                <el-button type="success" @click="handleStartAll" :loading="loading">
                  <el-icon><VideoPlay /></el-icon>
                  启动全部
                </el-button>
                <el-button type="warning" @click="handleStopAll" :loading="loading">
                  <el-icon><VideoPause /></el-icon>
                  停止全部
                </el-button>
                <el-button @click="loadStrategies" :loading="loading">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
              </el-space>
            </div>
          </template>

          <el-table :data="strategies" stripe v-loading="loading" table-layout="fixed">
            <el-table-column prop="strategy_id" label="策略ID" width="150" />
            <el-table-column prop="config.strategy_type" label="策略类型" width="100">
              <template #default="{ row }">
                <el-tag size="small">
                  {{ row.config.strategy_type === 'bar' ? 'K线策略' : row.config.strategy_type === 'tick' ? 'Tick策略' : '混合策略' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="config.symbol" label="合约" width="120">
              <template #default="{ row }">
                {{ row.config.symbol || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="config.exchange" label="交易所" width="100">
              <template #default="{ row }">
                {{ row.config.exchange || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="运行状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.active ? 'success' : 'info'" size="small">
                  {{ row.active ? '运行中' : '已停止' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="config.volume_per_trade" label="手数/次" width="90" />
            <el-table-column prop="config.max_position" label="最大持仓" width="90" />
            <el-table-column label="策略参数" min-width="200">
              <template #default="{ row }">
                <el-descriptions :column="1" size="small" border>
                  <el-descriptions-item v-if="row.config.rsi_period !== undefined" label="RSI周期">
                    {{ row.config.rsi_period }}
                  </el-descriptions-item>
                  <el-descriptions-item v-if="row.config.rsi_long_threshold !== undefined" label="多头阈值">
                    {{ row.config.rsi_long_threshold }}
                  </el-descriptions-item>
                  <el-descriptions-item v-if="row.config.rsi_short_threshold !== undefined" label="空头阈值">
                    {{ row.config.rsi_short_threshold }}
                  </el-descriptions-item>
                  <el-descriptions-item v-if="row.config.take_profit_pct !== undefined" label="止盈%">
                    {{ (row.config.take_profit_pct * 100).toFixed(1) }}%
                  </el-descriptions-item>
                  <el-descriptions-item v-if="row.config.stop_loss_pct !== undefined" label="止损%">
                    {{ (row.config.stop_loss_pct * 100).toFixed(1) }}%
                  </el-descriptions-item>
                </el-descriptions>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="!row.active"
                  type="success"
                  size="small"
                  @click="handleStartStrategy(row.strategy_id)"
                >
                  启动
                </el-button>
                <el-button
                  v-else
                  type="warning"
                  size="small"
                  @click="handleStopStrategy(row.strategy_id)"
                >
                  停止
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="strategies.length === 0" description="暂无策略" />
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
          {{ closeForm.offset === 'OPEN' ? '开仓' : closeForm.offset === 'CLOSE' ? '平仓' : '平今' }}
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
        <el-button type="danger" @click="handleClosePositionConfirm" :loading="closing">
          确认平仓
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
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { orderApi, positionApi, quoteApi, strategyApi } from '@/api'
import wsManager from '@/ws'
import type { ManualOrderRequest, Position, Order, Quote, StrategyRes } from '@/types'

const route = useRoute()
const store = useStore()
const loading = ref(false)
const loadingQuotes = ref(false)
const creating = ref(false)
const subscribing = ref(false)
const closing = ref(false)
const cancelling = ref(false)
const showOrderInputDialog = ref(false)
const showOrderConfirmDialog = ref(false)
const showCancelDialog = ref(false)
const showCloseDialog = ref(false)
const showSubscribeDialog = ref(false)
const activeTab = ref((route.query.tab as string) || 'account')
const orderTab = ref('PENDING')

const selectedOrders = ref<Order[]>([])
const quotes = ref<Quote[]>([])
const tradeDateFilter = ref(new Date().toISOString().split('T')[0])
const strategies = ref<StrategyRes[]>([])

const statusMap: Record<string, string> = {
  'PENDING': 'ALIVE',
  'FINISHED': 'FINISHED',
  'ERROR': 'REJECTED'
}

const orderForm = reactive<ManualOrderRequest>({
  symbol: '',
  direction: 'BUY',
  offset: 'OPEN',
  volume:1,
  price: null
})

const cancelForm = reactive({
  orderId: '',
  instrumentId: '',
  direction: 'BUY',
  offset: 'OPEN',
  volume: 0,
  price: 0
})

const closeForm = reactive({
  symbol: '',
  direction: 'BUY',
  offset: 'CLOSE',
  volume: 0,
  maxVolume: 0,
  price: 0
})

const subscribeForm = reactive({
  symbol: ''
})

const filteredTrades = computed(() => {
  return store.trades
})

function handleTickUpdate(tickData: Quote) {
  if (!tickData || !tickData.symbol) return

  const index = quotes.value.findIndex(q => q.symbol === tickData.symbol)
  if (index !== -1) {
    quotes.value[index] = {
      ...quotes.value[index],
      ...tickData
    }
  } else {
    quotes.value.push({
      ...tickData
    })
  }
}

async function loadAccountData() {
  loading.value = true
  try {
    await store.loadAccount()
  } finally {
    loading.value = false
  }
}

async function loadPositionData() {
  loading.value = true
  try {
    await store.loadPositions()
  } finally {
    loading.value = false
  }
}

async function loadOrderData() {
  loading.value = true
  try {
    const backendStatus = statusMap[orderTab.value]
    await store.loadOrders(backendStatus)
  } finally {
    loading.value = false
  }
}

async function loadTradeData() {
  loading.value = true
  try {
    await store.loadTrades(tradeDateFilter.value)
  } finally {
    loading.value = false
  }
}

async function loadQuotes() {
  loadingQuotes.value = true
  try {
    const result = await quoteApi.getSubscribedQuotes()
    quotes.value = result || []
  } catch (error: any) {
    ElMessage.error(`加载行情失败: ${error.message}`)
  } finally {
    loadingQuotes.value = false
  }
}

async function handleSubscribe() {
  if (!subscribeForm.symbol) {
    ElMessage.warning('请输入合约代码')
    return
  }

  subscribing.value = true
  try {
    await quoteApi.subscribeSymbol(subscribeForm.symbol)
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

async function loadStrategies() {
  loading.value = true
  try {
    strategies.value = await strategyApi.getStrategies()
  } catch (error: any) {
    ElMessage.error(`加载策略失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function handleStartStrategy(strategyId: string) {
  try {
    await strategyApi.startStrategy(strategyId)
    ElMessage.success(`策略 ${strategyId} 已启动`)
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`启动策略失败: ${error.message}`)
  }
}

async function handleStopStrategy(strategyId: string) {
  try {
    await strategyApi.stopStrategy(strategyId)
    ElMessage.success(`策略 ${strategyId} 已停止`)
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`停止策略失败: ${error.message}`)
  }
}

async function handleStartAll() {
  try {
    await strategyApi.startAllStrategies()
    ElMessage.success('所有策略已启动')
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`启动策略失败: ${error.message}`)
  }
}

async function handleStopAll() {
  try {
    await strategyApi.stopAllStrategies()
    ElMessage.success('所有策略已停止')
    await loadStrategies()
  } catch (error: any) {
    ElMessage.error(`停止策略失败: ${error.message}`)
  }
}



function handleOrderSelectionChange(selection: Order[]) {
  selectedOrders.value = selection
}

function handleClosePosition(position: Position, direction: 'BUY' | 'SELL') {
  const volume = direction === 'SELL' ? position.pos_long : position.pos_short
  if (volume <= 0) return

  closeForm.symbol = position.instrument_id
  closeForm.direction = direction
  closeForm.offset = 'CLOSE'
  closeForm.volume = volume
  closeForm.maxVolume = volume
  closeForm.price = 0

  showCloseDialog.value = true
}


async function handleCreateOrder() {
  if (!orderForm.symbol || !orderForm.direction || !orderForm.offset || orderForm.volume <= 0) {
    ElMessage.warning('请填写完整的报单信息')
    return
  }

  creating.value = true
  try {
    const result = await orderApi.createOrder(orderForm)
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
  const order = store.orders.find(o => o.order_id === orderId)
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
    await orderApi.cancelOrder(cancelForm.orderId)
    ElMessage.success('撤单成功')
    showCancelDialog.value = false
    await loadOrderData()
  } catch (error: any) {
    ElMessage.error(`撤单失败: ${error.message}`)
    showCancelDialog.value = false
  }
}

async function handleClosePositionConfirm() {
  try {
    await positionApi.closePosition({
      symbol: closeForm.symbol,
      direction: closeForm.direction,
      offset: closeForm.offset,
      volume: closeForm.volume,
      price: closeForm.price
    })
    ElMessage.success('平仓成功')
    showCloseDialog.value = false
    await loadPositionData()
  } catch (error: any) {
    ElMessage.error(`平仓失败: ${error.message}`)
    showCloseDialog.value = false
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
  } else if (newTab === 'account') {
    loadAccountData()
    loadPositionData()
  } else if (newTab === 'trade') {
    loadTradeData()
  } else if (newTab === 'strategy') {
    loadStrategies()
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

onMounted(() => {
  if (activeTab.value === 'trading') {
    loadQuotes()
    loadOrderData()
  } else if (activeTab.value === 'account') {
    loadAccountData()
    loadPositionData()
  } else if (activeTab.value === 'trade') {
    loadTradeData()
  } else if (activeTab.value === 'strategy') {
    loadStrategies()
  }

  wsManager.onTickUpdate(handleTickUpdate)
})

onUnmounted(() => {
  wsManager.onTickUpdate(handleTickUpdate)()
})
</script>

<style scoped>
.account-tabs {
  padding: 0;
  width: 100%;
}

.account-tabs-inner {
  width: 100%;
}

.account-tabs-inner .el-tabs__content {
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

.mb-4 {
  margin-bottom: 16px;
}
</style>
