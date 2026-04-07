<template>
  <div class="account-combined">
    <el-tabs v-model="activeTab" class="account-tabs">
      <!-- 账户详情 Tab -->
      <el-tab-pane label="账户详情" name="detail">
        <el-card shadow="hover" v-if="store.currentAccount">
          <template #header>
            <div class="card-header">
              <span>账户信息</span>
              <div>
                <el-button type="primary" @click="loadAccountData" :loading="loading">
                  <el-icon><Refresh /></el-icon>
                  刷新
                </el-button>
              </div>
            </div>
          </template>

          <el-descriptions :column="descColumn" border>
            <el-descriptions-item label="用户ID">{{ store.currentAccount.user_id || '-'}}</el-descriptions-item>
            <el-descriptions-item label="经纪商">
              {{ store.currentAccount.broker_name || '-' }}
              <el-tag v-if="store.currentAccount.broker_type" size="small" style="margin-left: 8px">
                {{ getBrokerTypeName(store.currentAccount.broker_type) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="总资产">
              <span class="balance">¥{{ formatNumber(store.currentAccount.balance) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="静态权益">
              <span class="available">¥{{ formatNumber(store.currentAccount.static_balance) }}</span>
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
            <el-descriptions-item label="保证金占用">
              ¥{{ formatNumber(store.currentAccount.margin) }}
               <el-tag :type="store.currentAccount.risk_ratio > 1 ? 'danger' : 'success'">
                {{ formatNumber(store.currentAccount.risk_ratio*100) }}%
              </el-tag>
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

          <div class="table-wrapper">
            <el-table
              :data="store.currentPositions"
              stripe
              v-loading="loading"
              table-layout="fixed"
            >
              <template #empty>
                <el-empty description="暂无持仓" />
              </template>
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
              <el-table-column label="多头均价" width="110">
                <template #default="{ row }">
                  {{ row.pos_long > 0 ? formatNumber(row.hold_price_long) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="空头均价" width="110">
                <template #default="{ row }">
                  {{ row.pos_short > 0 ? formatNumber(row.hold_price_short) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="保证金" width="110">
                <template #default="{ row }">
                  ¥{{ formatNumber((row.margin_long || 0) + (row.margin_short || 0)) }}
                </template>
              </el-table-column>
              <el-table-column label="持仓盈亏" width="130">
                <template #default="{ row }">
                  <span :class="(row.hold_profit_long || 0) + (row.hold_profit_short || 0) >= 0 ? 'profit' : 'loss'">
                    ¥{{ formatNumber((row.hold_profit_long || 0) + (row.hold_profit_short || 0)) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="平仓盈亏" width="130">
                <template #default="{ row }">
                  <span :class="(row.close_profit_long || 0) + (row.close_profit_short || 0) >= 0 ? 'profit' : 'loss'">
                    ¥{{ formatNumber((row.close_profit_long || 0) + (row.close_profit_short || 0)) }}
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
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 交易 Tab -->
      <el-tab-pane label="账户交易" name="trading">
        <el-row :gutter="20">
          <el-col :xs="24" :lg="6">
            <el-card shadow="hover" class="quote-card">
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

              <div class="table-wrapper">
                <el-table
                  :data="store.currentOrders"
                  stripe
                  v-loading="loading"
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
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- 成交记录 Tab -->
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

          <div class="table-wrapper">
            <el-table :data="sortedTrades" stripe v-loading="loading">
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
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 报单指令 Tab -->
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
                v-if="orderCmdStatus === 'active'"
                label="操作"
                width="100"
                fixed="right"
              >
                <template #default="{ row }">
                  <el-button
                    type="danger"
                    size="small"
                    @click="handleCancelOrderCmd(row.cmd_id)"
                    :loading="cancellingCmdId === row.cmd_id"
                  >
                    取消
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 合约信息 Tab -->
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
                <el-button type="warning" @click="handleRefreshContracts" :loading="refreshingContracts">
                  <el-icon><Download /></el-icon>
                  强制同步
                </el-button>
              </el-space>
            </div>
          </template>

          <div class="table-wrapper">
            <el-table :data="contracts" stripe v-loading="loading">
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
              <el-table-column prop="update_date" label="更新日期" />
            </el-table>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 设置 Tab -->
      <el-tab-pane label="账户设置" name="setting">
        <el-row :gutter="20">
          <!-- 系统状态 -->
          <el-col :span="24">
            <el-card shadow="hover">
              <template #header>
                <div class="card-header">
                  <span>系统控制</span>
                </div>
              </template>

              <el-descriptions :column="descColumn" border>
                <el-descriptions-item label="连接状态">
                  <el-tag :type="getAccountStatusType(store.currentAccount)" size="large">
                    {{ getAccountStatusText(store.currentAccount) }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="交易状态">
                  <el-tag
                    v-if="store.currentAccount?.status === 'connected'"
                    :type="store.currentAccount?.trade_paused ? 'warning' : 'success'"
                    size="large"
                  >
                    {{ store.currentAccount?.trade_paused ? '已暂停' : '正常' }}
                  </el-tag>
                  <span v-else>-</span>
                </el-descriptions-item>
                <el-descriptions-item label="今日报单">
                  {{ currentRiskStatus.daily_order_count }} 次
                </el-descriptions-item>
                <el-descriptions-item label="今日撤单">
                  {{ currentRiskStatus.daily_cancel_count }} 次
                </el-descriptions-item>
              </el-descriptions>
            </el-card>
          </el-col>
        </el-row>

        <el-row :gutter="20" class="mt-4">
          <!-- 风控参数配置 -->
          <el-col :span="24">
            <el-card shadow="hover">
              <template #header>
                <div class="card-header">
                  <span>风控参数配置</span>
                </div>
              </template>

              <el-form :model="riskForm" label-width="140px">
                <el-row :gutter="20">
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="单日最大报单次数">
                      <el-input-number
                        v-model="riskForm.max_daily_orders"
                        :min="0"
                        :disabled="updatingRisk"
                      />
                      <span class="ml-2">今日: {{ currentRiskStatus.daily_order_count }} / {{ currentRiskStatus.max_daily_orders }}</span>
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="单日最大撤单次数">
                      <el-input-number
                        v-model="riskForm.max_daily_cancels"
                        :min="0"
                        :disabled="updatingRisk"
                      />
                      <span class="ml-2">今日: {{ currentRiskStatus.daily_cancel_count }} / {{ currentRiskStatus.max_daily_cancels }}</span>
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-row :gutter="20">
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="单笔最大报单手数">
                      <el-input-number
                        v-model="riskForm.max_order_volume"
                        :min="1"
                        :disabled="updatingRisk"
                      />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="单笔最大拆单手数">
                      <el-input-number
                        v-model="riskForm.max_split_volume"
                        :min="1"
                        :disabled="updatingRisk"
                      />
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-row :gutter="20">
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="报单超时时间（秒）">
                      <el-input-number
                        v-model="riskForm.order_timeout"
                        :min="1"
                        :disabled="updatingRisk"
                      />
                    </el-form-item>
                  </el-col>
                </el-row>
                <el-form-item>
                  <el-button
                    type="primary"
                    @click="updateRiskControl"
                    :loading="updatingRisk"
                  >
                    保存配置
                  </el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>
        </el-row>

        <el-row :gutter="20" class="mt-4">
          <!-- 定时任务列表（独占一行） -->
          <el-col :span="24">
            <el-card shadow="hover">
              <template #header>
                <div class="card-header">
                  <span>定时任务列表</span>
                  <el-button @click="loadTasks" :loading="loadingTasks">
                    <el-icon><Refresh /></el-icon>
                    刷新
                  </el-button>
                </div>
              </template>

              <div class="table-wrapper">
                <el-table :data="tasks" stripe v-loading="loadingTasks" table-layout="fixed">
                  <template #empty>
                    <el-empty description="暂无定时任务" />
                  </template>
                  <el-table-column prop="job_name" label="任务名称" min-width="200" />
                  <el-table-column prop="job_group" label="分组" width="120" />
                  <el-table-column prop="job_description" label="描述" min-width="200" show-overflow-tooltip />
                  <el-table-column prop="cron_expression" label="Cron表达式" width="150" />
                  <el-table-column label="上次触发时间" width="180">
                    <template #default="{ row }">
                      {{ row.last_trigger_time ? formatDateTime(row.last_trigger_time) : '-' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                      <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                        {{ row.enabled ? '就绪' : '暂停' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="200" fixed="right">
                    <template #default="{ row }">
                      <el-space>
                        <el-button
                          v-if="row.enabled"
                          type="warning"
                          size="small"
                          @click="handleOperateJob(row, 'pause')"
                          :loading="operatingJob === `${row.job_id}_pause`"
                        >
                          暂停
                        </el-button>
                        <el-button
                          v-else
                          type="success"
                          size="small"
                          @click="handleOperateJob(row, 'resume')"
                          :loading="operatingJob === `${row.job_id}_resume`"
                        >
                          恢复
                        </el-button>
                        <el-button
                          type="primary"
                          size="small"
                          @click="handleOperateJob(row, 'trigger')"
                          :loading="operatingJob === `${row.job_id}_trigger`"
                        >
                          立即触发
                        </el-button>
                      </el-space>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-card>
          </el-col>
        </el-row>
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
import { ref, reactive, watch, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useStore } from '@/stores'
import { positionApi, orderApi, quoteApi, orderCmdApi, contractApi, systemApi, jobsApi } from '@/api'
import wsManager from '@/ws'
import type { Position, ManualOrderRequest, Order, Quote, OrderCmd, ContractInfo, ExchangeInfo, Job, RiskControlStatus, Account } from '@/types'

const store = useStore()
const loading = ref(false)
const creating = ref(false)
const subscribing = ref(false)
const cancelling = ref(false)
const descColumn = ref(2)

// Tab 相关
const activeTab = ref('detail')
const orderTab = ref('PENDING')

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
  product_type: '',
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

// 设置页面 - 风控状态
const currentRiskStatus = computed<RiskControlStatus>(() => {
  return store.currentAccount?.risk_status || {
    daily_order_count: 0,
    daily_cancel_count: 0,
    max_daily_orders: 100,
    max_daily_cancels: 50,
    max_order_volume: 50,
    max_split_volume: 5,
    order_timeout: 5,
    remaining_orders: 100,
    remaining_cancels: 50
  }
})

const riskForm = reactive({
  max_daily_orders: 100,
  max_daily_cancels: 50,
  max_order_volume: 50,
  max_split_volume: 5,
  order_timeout: 5
})

// 响应式列数
function updateDescColumn() {
  descColumn.value = window.innerWidth <= 768 ? 1 : 2
}

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
    const backendStatus = statusMap[orderTab.value]
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

// 按时间倒序排序的成交记录
const sortedTrades = computed(() => {
  if (!store.currentTrades || store.currentTrades.length === 0) return []
  return [...store.currentTrades].sort((a, b) => {
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

// 按开始时间倒序排序的报单指令
const sortedOrderCmds = computed(() => {
  if (!orderCmds.value || orderCmds.value.length === 0) return []
  return [...orderCmds.value].sort((a, b) => {
    const timeA = a.started_at ? new Date(a.started_at).getTime() : 0
    const timeB = b.started_at ? new Date(b.started_at).getTime() : 0
    return timeB - timeA
  })
})

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
function getAccountStatusType(account: Account | null): string {
  if (!account) return 'info'
  switch (account.status) {
    case 'connected':
      return 'success'
    case 'connecting':
      return 'warning'
    case 'stopped':
    default:
      return 'info'
  }
}

function getAccountStatusText(account: Account | null): string {
  if (!account) return '未连接'
  switch (account.status) {
    case 'connected':
      return '已连接'
    case 'connecting':
      return '连接中'
    case 'stopped':
    default:
      return '已停止'
  }
}

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

function getBrokerTypeName(type: string | null): string {
  const typeMap: Record<string, string> = {
    'tq': '天勤',
    'sim': '模拟',
    'kq': '快期',
    'ctp': 'CTP',
  }
  return typeMap[type || ''] || type || ''
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

// ========== 监听 ==========
watch(activeTab, (newTab) => {
  if (newTab === 'detail') {
    loadAccountData()
    loadPositionData()
  } else if (newTab === 'trading') {
    loadQuotes()
    loadOrderData()
  } else if (newTab === 'trade') {
    loadTradeData()
  } else if (newTab === 'order-cmd') {
    loadOrderCmdData()
  } else if (newTab === 'contract') {
    loadContracts()
  } else if (newTab === 'setting') {
    loadTasks()
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

watch(tradeDateFilter, () => {
  if (activeTab.value === 'trade') {
    loadTradeData()
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
  updateDescColumn()
  window.addEventListener('resize', updateDescColumn)

  // 初始加载
  if (activeTab.value === 'detail') {
    await loadAccountData()
    await loadPositionData()
  } else if (activeTab.value === 'trading') {
    await loadQuotes()
    await loadOrderData()
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
  window.removeEventListener('resize', updateDescColumn)
  wsManager.onTickUpdate(handleTickUpdate)()
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

.quote-card,
.order-card {
  margin-bottom: 12px;
}

.mt-4 {
  margin-top: 20px;
}

.ml-2 {
  margin-left: 8px;
}
</style>
