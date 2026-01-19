<template>
  <div class="dashboard">
    <el-row :gutter="20">
      <!-- 账户概览 -->
      <el-col :span="6" v-if="store.account">
        <el-card shadow="hover">
          <el-statistic title="总资产" :value="store.account.balance" :precision="2" prefix="¥" />
        </el-card>
      </el-col>
      <el-col :span="6" v-if="store.account">
        <el-card shadow="hover">
          <el-statistic title="可用资金" :value="store.account.available" :precision="2" prefix="¥" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic
            title="持仓数量"
            :value="store.positions.length"
            suffix="个"
          />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic
            title="活跃委托"
            :value="store.activeOrders.length"
            suffix="单"
          />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <!-- 盈亏统计 -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>盈亏统计</span>
            </div>
          </template>
          <div v-if="store.account">
            <el-row :gutter="20">
              <el-col :span="12">
                <div class="stat-item">
                  <div class="stat-label">浮动盈亏</div>
                  <div class="stat-value" :class="store.account.float_profit >= 0 ? 'profit' : 'loss'">
                    ¥{{ formatNumber(store.account.float_profit) }}
                  </div>
                </div>
              </el-col>
              <el-col :span="12">
                <div class="stat-item">
                  <div class="stat-label">平仓盈亏</div>
                  <div class="stat-value" :class="store.account.close_profit >= 0 ? 'profit' : 'loss'">
                    ¥{{ formatNumber(store.account.close_profit) }}
                  </div>
                </div>
              </el-col>
            </el-row>
          </div>
        </el-card>
      </el-col>

      <!-- 风控统计 -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>今日风控</span>
            </div>
          </template>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-progress
                :percentage="getOrderPercentage()"
                :color="getProgressColor(getOrderPercentage())"
                :stroke-width="20"
              />
              <div class="progress-label">
                今日报单: {{ store.systemStatus.daily_orders }} / {{ riskControlStatus.max_daily_orders }}
              </div>
            </el-col>
            <el-col :span="12">
              <el-progress
                :percentage="getCancelPercentage()"
                :color="getProgressColor(getCancelPercentage())"
                :stroke-width="20"
              />
              <div class="progress-label">
                今日撤单: {{ store.systemStatus.daily_cancels }} / {{ riskControlStatus.max_daily_cancels }}
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <!-- 告警统计 -->
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>告警统计</span>
              <el-link type="primary" @click="$router.push('/account?tab=alarm')">查看全部</el-link>
            </div>
          </template>
          <el-row :gutter="20">
            <el-col :span="8">
              <div class="stat-item">
                <div class="stat-label">今日总告警</div>
                <div class="stat-value" :class="alarmStats.today_total > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.today_total }}
                </div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="stat-item">
                <div class="stat-label">最近1小时告警</div>
                <div class="stat-value" :class="alarmStats.last_hour > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.last_hour }}
                </div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="stat-item">
                <div class="stat-label">最近5分钟告警</div>
                <div class="stat-value" :class="alarmStats.last_five_minutes > 0 ? 'loss' : 'profit'">
                  {{ alarmStats.last_five_minutes }}
                </div>
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <!-- 最近成交 -->
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>最近成交</span>
              <el-link type="primary" @click="$router.push('/account?tab=trade')">查看全部</el-link>
            </div>
          </template>
          <el-table :data="store.trades.slice(0, 5)" stripe>
            <el-table-column prop="trade_id" label="成交ID" width="180" />
            <el-table-column prop="symbol" label="合约" width="120" />
            <el-table-column prop="direction" label="方向" width="80">
              <template #default="{ row }">
                <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small">
                  {{ row.direction === 'BUY' ? '买' : '卖' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="offset" label="开平" width="80" />
            <el-table-column prop="price" label="价格" width="100">
              <template #default="{ row }">
                {{ formatNumber(row.price) }}
              </template>
            </el-table-column>
            <el-table-column prop="volume" label="手数" width="80" />
            <el-table-column prop="created_at" label="时间">
              <template #default="{ row }">
                {{ formatDateTime(row.trade_date_time) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useStore } from '@/stores'
import { alarmApi, systemApi } from '@/api'
import type { RiskControlStatus } from '@/types'

const store = useStore()
const alarmStats = ref({ today_total: 0, last_hour: 0, last_five_minutes: 0 })
const riskControlStatus = ref<RiskControlStatus>({
  daily_order_count: 0,
  daily_cancel_count: 0,
  max_daily_orders: 100,
  max_daily_cancels: 50,
  max_order_volume: 50,
  max_split_volume: 5,
  order_timeout: 5,
  remaining_orders: 100,
  remaining_cancels: 50
})

async function loadAlarmStats() {
  try {
    const result = await alarmApi.getAlarmStats()
    alarmStats.value = result || { today_total: 0, last_hour: 0, last_five_minutes: 0 }
  } catch (error: any) {
    console.error(`加载告警统计失败: ${error.message}`)
  }
}

async function loadRiskControl() {
  try {
    const data = await systemApi.getRiskControlStatus()
    riskControlStatus.value = data
  } catch (error: any) {
    console.error(`加载风控状态失败: ${error.message}`)
  }
}

onMounted(() => {
  loadAlarmStats()
  loadRiskControl()
})

// 格式化数字
function formatNumber(num: number): string {
  return num.toFixed(2)
}

// 格式化日期时间
function formatDateTime(datetime: string): string {
  return new Date(datetime).toLocaleString('zh-CN')
}

// 计算报单百分比
function getOrderPercentage(): number {
  if (riskControlStatus.value.max_daily_orders === 0) return 0
  const percentage = (store.systemStatus.daily_orders / riskControlStatus.value.max_daily_orders) * 100
  return parseFloat(percentage.toFixed(1))
}

// 计算撤单百分比
function getCancelPercentage(): number {
  if (riskControlStatus.value.max_daily_cancels === 0) return 0
  const percentage = (store.systemStatus.daily_cancels / riskControlStatus.value.max_daily_cancels) * 100
  return parseFloat(percentage.toFixed(1))
}

// 进度条颜色
function getProgressColor(percentage: number): string {
  if (percentage >= 80) return '#f56c6c'
  if (percentage >= 60) return '#e6a23c'
  return '#67c23a'
}
</script>

<style scoped>
.dashboard {
  padding: 0;
}

.mt-4 {
  margin-top: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-item {
  text-align: center;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-bottom: 10px;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
}

.profit {
  color: #67c23a;
}

.loss {
  color: #f56c6c;
}

.progress-label {
  text-align: center;
  margin-top: 10px;
  font-size: 12px;
  color: #606266;
}
</style>
