<template>
  <div class="system">
    <el-row :gutter="20">
      <!-- 系统状态 -->
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>系统控制</span>
            </div>
          </template>

          <el-descriptions :column="2" border>
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
              <el-col :span="12">
                <el-form-item label="单日最大报单次数">
                  <el-input-number
                    v-model="riskForm.max_daily_orders"
                    :min="0"
                    :disabled="updatingRisk"
                  />
                  <span class="ml-2">今日: {{ currentRiskStatus.daily_order_count }} / {{ currentRiskStatus.max_daily_orders }}</span>
                </el-form-item>
              </el-col>
              <el-col :span="12">
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
              <el-col :span="12">
                <el-form-item label="单笔最大报单手数">
                  <el-input-number
                    v-model="riskForm.max_order_volume"
                    :min="1"
                    :disabled="updatingRisk"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
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
              <el-col :span="12">
                <el-form-item label="报单超时时间（秒）">
                  <el-input-number
                    v-model="riskForm.order_timeout"
                    :min="1"
                    :disabled="updatingRisk"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="微信告警">
                  <el-switch
                    v-model="alertWechat"
                    :disabled="updatingAlertWechat"
                    active-text="启用"
                    inactive-text="禁用"
                  />
                  <span class="ml-2" v-if="alertWechat">订单拒绝/策略报单时发送微信通知</span>
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

          <el-table :data="tasks" stripe v-loading="loadingTasks" height="300" table-layout="fixed">
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

          <el-empty v-if="tasks.length === 0" description="暂无定时任务" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 连接对话框 -->
    <el-dialog v-model="showConnectDialog" title="连接交易系统" width="400px">
      <el-form :model="connectForm" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="connectForm.username" placeholder="天勤账号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="connectForm.password" type="password" placeholder="天勤密码" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showConnectDialog = false">取消</el-button>
        <el-button type="primary" @click="handleConnect" :loading="connecting">
          连接
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { ElMessage, ElSpace } from 'element-plus'
import { useStore } from '@/stores'
import { systemApi, accountApi } from '@/api'
import { jobsApi } from '@/api'
import type { Job, RiskControlStatus, Account } from '@/types'
import wsManager from '@/ws'

// 获取账户状态标签类型
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

// 获取账户状态文本
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

const store = useStore()
const connecting = ref(false)
const showConnectDialog = ref(false)
const updatingRisk = ref(false)
const updatingAlertWechat = ref(false)
const loadingTasks = ref(false)
const operatingJob = ref<string | null>(null)
const tasks = ref<Job[]>([])
const alertWechat = ref(false)

const connectForm = reactive({
  username: '',
  password: ''
})

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

// 监听 alertWechat 变化，自动保存
watch(alertWechat, async (newValue) => {
  await updateAlertWechat(newValue)
})

async function updateAlertWechat(value: boolean) {
  updatingAlertWechat.value = true
  try {
    await systemApi.updateAlertWechat(value, store.selectedAccountId || undefined)
    ElMessage.success('微信告警配置已更新')
    await store.loadAllAccounts()
  } catch (error: any) {
    console.error('更新微信告警配置失败:', error)
    ElMessage.error(`更新微信告警配置失败: ${error.message}`)
    // 更新失败时恢复原值
    await loadAlertWechat()
  } finally {
    updatingAlertWechat.value = false
  }
}

async function loadAlertWechat() {
  try {
    const result = await systemApi.getAlertWechat(store.selectedAccountId || undefined)
    alertWechat.value = result.alert_wechat
  } catch (error: any) {
    console.error('获取微信告警配置失败:', error)
  }
}

// 监听当前账户变化，重新加载 alert_wechat
watch(() => store.selectedAccountId, () => {
  if (store.selectedAccountId) {
    loadAlertWechat()
  }
})

onMounted(() => {
  loadTasks()
  if (store.selectedAccountId) {
    loadAlertWechat()
  }
})

async function handleConnect() {
  connecting.value = true
  try {
    await accountApi.connectGateway(store.selectedAccountId || '')
    ElMessage.success('连接成功')
    showConnectDialog.value = false
    await store.loadAllAccounts()
    if (!wsManager.connected.value) {
      wsManager.connect()
    }
  } catch (error: any) {
    ElMessage.error(`连接失败: ${error.message}`)
  } finally {
    connecting.value = false
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
    // 多账号模式：传递当前选中的账户ID
    const accountId = store.isMultiAccountMode ? (store.selectedAccountId || undefined) : undefined
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

function formatDateTime(datetime: string): string {
  return new Date(datetime).toLocaleString('zh-CN')
}

onMounted(() => {
  loadTasks()
})
</script>

<style scoped>
.system {
  padding: 0;
  width: 100%;
}

.mt-4 {
  margin-top: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
