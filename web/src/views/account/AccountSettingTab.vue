<template>
  <div class="account-setting-tab">
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

          <el-form :model="localRiskForm" label-width="140px">
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="单日最大报单次数">
                  <el-input-number
                    v-model="localRiskForm.max_daily_orders"
                    :min="0"
                    :disabled="updating"
                  />
                  <span class="ml-2">今日: {{ currentRiskStatus.daily_order_count }} / {{ currentRiskStatus.max_daily_orders }}</span>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="单日最大撤单次数">
                  <el-input-number
                    v-model="localRiskForm.max_daily_cancels"
                    :min="0"
                    :disabled="updating"
                  />
                  <span class="ml-2">今日: {{ currentRiskStatus.daily_cancel_count }} / {{ currentRiskStatus.max_daily_cancels }}</span>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="单笔最大报单手数">
                  <el-input-number
                    v-model="localRiskForm.max_order_volume"
                    :min="1"
                    :disabled="updating"
                  />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="单笔最大拆单手数">
                  <el-input-number
                    v-model="localRiskForm.max_split_volume"
                    :min="1"
                    :disabled="updating"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="报单超时时间（秒）">
                  <el-input-number
                    v-model="localRiskForm.order_timeout"
                    :min="1"
                    :disabled="updating"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item>
              <el-button
                type="primary"
                @click="emit('updateRiskControl')"
                :loading="updating"
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
              <el-button @click="emit('refreshTasks')" :loading="loadingTasks">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </template>

          <div class="table-wrapper">
            <el-table
              :data="tasks"
              data-testid="jobs-table"
              stripe
              v-loading="loadingTasks"
              table-layout="fixed"
              :size="isMobile ? 'small' : 'default'"
            >
              <template #empty>
                <el-empty description="暂无定时任务" />
              </template>
              <el-table-column prop="job_name" label="任务名称" :min-width="isMobile ? 120 : 200" />
              <el-table-column prop="job_group" label="分组" :width="isMobile ? 70 : 120" />
              <el-table-column v-if="!isMobile" prop="job_description" label="描述" min-width="200" show-overflow-tooltip />
              <el-table-column v-if="!isMobile" prop="cron_expression" label="Cron表达式" width="150" />
              <el-table-column v-if="!isMobile" label="上次触发时间" width="180">
                <template #default="{ row }">
                  {{ row.last_trigger_time ? formatDateTime(row.last_trigger_time) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="状态" :width="isMobile ? 60 : 100">
                <template #default="{ row }">
                  <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                    {{ row.enabled ? '就绪' : '暂停' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" :width="isMobile ? 160 : 200">
                <template #default="{ row }">
                  <el-space>
                    <el-button
                      v-if="row.enabled"
                      type="warning"
                      :size="isMobile ? 'small' : 'default'"
                      @click="emit('operateJob', row, 'pause')"
                      :loading="operatingJob === `${row.job_id}_pause`"
                    >
                      暂停
                    </el-button>
                    <el-button
                      v-else
                      type="success"
                      :size="isMobile ? 'small' : 'default'"
                      @click="emit('operateJob', row, 'resume')"
                      :loading="operatingJob === `${row.job_id}_resume`"
                    >
                      恢复
                    </el-button>
                    <el-button
                      type="primary"
                      :size="isMobile ? 'small' : 'default'"
                      @click="emit('operateJob', row, 'trigger')"
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useStore } from '@/stores'
import type { Job, RiskControlStatus, Account } from '@/types'

const store = useStore()
const descColumn = ref(2)
const isMobile = ref(false)
const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 768
}

interface RiskForm {
  max_daily_orders: number
  max_daily_cancels: number
  max_order_volume: number
  max_split_volume: number
  order_timeout: number
}

const props = defineProps<{
  loadingTasks: boolean
  operatingJob: string | null
  tasks: Job[]
  updating: boolean
  riskForm: RiskForm
}>()

const emit = defineEmits<{
  refreshTasks: []
  operateJob: [row: Job, action: 'pause' | 'resume' | 'trigger']
  updateRiskControl: []
  'update:riskForm': [form: RiskForm]
}>()

const localRiskForm = computed({
  get: () => props.riskForm,
  set: (val) => emit('update:riskForm', val)
})

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

function updateDescColumn() {
  descColumn.value = window.innerWidth <= 768 ? 1 : 2
}

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

function formatDateTime(datetime: string | number | null | undefined): string {
  if (!datetime) return '-'
  const date = typeof datetime === 'number'
    ? new Date(datetime * 1000)
    : new Date(datetime)
  return date.toLocaleString('zh-CN')
}

onMounted(() => {
  updateDescColumn()
  updateIsMobile()
  window.addEventListener('resize', updateDescColumn)
  window.addEventListener('resize', updateIsMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateDescColumn)
  window.removeEventListener('resize', updateIsMobile)
})
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

.mt-4 {
  margin-top: 20px;
}

.ml-2 {
  margin-left: 8px;
}
</style>
