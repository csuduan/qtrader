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
              <el-tag :type="store.systemStatus.connected ? 'success' : 'danger'" size="large">
                {{ store.systemStatus.connected ? '已连接' : '未连接' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="交易状态">
              <el-tag
                v-if="store.systemStatus.connected"
                :type="store.systemStatus.paused ? 'warning' : 'success'"
                size="large"
              >
                {{ store.systemStatus.paused ? '已暂停' : '正常' }}
              </el-tag>
              <span v-else>-</span>
            </el-descriptions-item>
            <el-descriptions-item label="今日报单">
              {{ store.systemStatus.daily_orders }} 次
            </el-descriptions-item>
            <el-descriptions-item label="今日撤单">
              {{ store.systemStatus.daily_cancels }} 次
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <!-- 交易控制面板（合并连接和交易控制） -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>交易控制</span>
            </div>
          </template>

          <el-space direction="vertical" :size="20" style="width: 100%">
            <!-- 连接控制 -->
            <div class="control-section">
              <div class="section-title">连接控制</div>
              <el-button
                v-if="!store.systemStatus.connected"
                type="primary"
                size="large"
                @click="handleConnect"
                :loading="connecting"
              >
                <el-icon><Connection /></el-icon>
                连接系统
              </el-button>

              <el-button
                v-else
                type="danger"
                size="large"
                @click="handleDisconnect"
                :loading="disconnecting"
              >
                <el-icon><SwitchButton /></el-icon>
                断开连接
              </el-button>
            </div>

            <!-- 交易控制 -->
            <div class="control-section">
              <div class="section-title">交易控制</div>
              <el-button
                v-if="store.systemStatus.connected && store.systemStatus.paused"
                type="success"
                size="large"
                @click="handleResume"
                :loading="resuming"
              >
                <el-icon><VideoPlay /></el-icon>
                恢复交易
              </el-button>

              <el-button
                v-if="store.systemStatus.connected && !store.systemStatus.paused"
                type="warning"
                size="large"
                @click="handlePause"
                :loading="pausing"
              >
                <el-icon><VideoPause /></el-icon>
                暂停交易
              </el-button>

              <el-alert
                v-if="!store.systemStatus.connected"
                title="请先连接系统"
                type="info"
                :closable="false"
              />
            </div>
          </el-space>
        </el-card>
      </el-col>

      <!-- 风控参数配置 -->
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>风控参数配置</span>
              <el-button @click="loadRiskControl" :loading="loadingRisk">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </template>

          <el-form :model="riskForm" label-width="140px">
            <el-form-item label="单日最大报单次数">
              <el-input-number
                v-model="riskForm.max_daily_orders"
                :min="0"
                :disabled="updatingRisk"
              />
              <span class="ml-2">今日: {{ riskControlStatus.daily_order_count }} / {{ riskControlStatus.max_daily_orders }}</span>
            </el-form-item>
            <el-form-item label="单日最大撤单次数">
              <el-input-number
                v-model="riskForm.max_daily_cancels"
                :min="0"
                :disabled="updatingRisk"
              />
              <span class="ml-2">今日: {{ riskControlStatus.daily_cancel_count }} / {{ riskControlStatus.max_daily_cancels }}</span>
            </el-form-item>
            <el-form-item label="单笔最大报单手数">
              <el-input-number
                v-model="riskForm.max_order_volume"
                :min="1"
                :disabled="updatingRisk"
              />
            </el-form-item>
            <el-form-item label="单笔最大拆单手数">
              <el-input-number
                v-model="riskForm.max_split_volume"
                :min="1"
                :disabled="updatingRisk"
              />
            </el-form-item>
            <el-form-item label="报单超时时间（秒）">
              <el-input-number
                v-model="riskForm.order_timeout"
                :min="1"
                :disabled="updatingRisk"
              />
            </el-form-item>
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ElSpace } from 'element-plus'
import { useStore } from '@/stores'
import { systemApi } from '@/api'
import { jobsApi } from '@/api'
import type { Job, RiskControlStatus } from '@/types'
import wsManager from '@/ws'

const store = useStore()
const connecting = ref(false)
const disconnecting = ref(false)
const pausing = ref(false)
const resuming = ref(false)
const showConnectDialog = ref(false)
const loadingRisk = ref(false)
const updatingRisk = ref(false)
const loadingTasks = ref(false)
const operatingJob = ref<string | null>(null)

const connectForm = reactive({
  username: '',
  password: ''
})

const riskControlStatus = reactive<RiskControlStatus>({
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

const riskForm = reactive({
  max_daily_orders: 100,
  max_daily_cancels: 50,
  max_order_volume: 50,
  max_split_volume: 5,
  order_timeout: 5
})

const tasks = ref<Job[]>([])

async function handleConnect() {
  connecting.value = true
  try {
    await systemApi.connect(connectForm.username, connectForm.password)
    ElMessage.success('连接成功')
    showConnectDialog.value = false
    await store.loadSystemStatus()
    if (!wsManager.connected.value) {
      wsManager.connect()
    }
  } catch (error: any) {
    ElMessage.error(`连接失败: ${error.message}`)
  } finally {
    connecting.value = false
  }
}

async function handleDisconnect() {
  try {
    await ElMessageBox.confirm('确定要断开连接吗？', '确认断开', {
      type: 'warning'
    })

    disconnecting.value = true
    await systemApi.disconnect()
    ElMessage.success('已断开连接')
    await store.loadSystemStatus()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`断开失败: ${error.message}`)
    }
  } finally {
    disconnecting.value = false
  }
}

async function handlePause() {
  try {
    await ElMessageBox.confirm('确定要暂停交易吗？', '确认暂停', {
      type: 'warning'
    })

    pausing.value = true
    await systemApi.pause()
    ElMessage.success('交易已暂停')
    await store.loadSystemStatus()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`暂停失败: ${error.message}`)
    }
  } finally {
    pausing.value = false
  }
}

async function handleResume() {
  try {
    await ElMessageBox.confirm('确定要恢复交易吗？', '确认恢复', {
      type: 'success'
    })

    resuming.value = true
    await systemApi.resume()
    ElMessage.success('交易已恢复')
    await store.loadSystemStatus()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`恢复失败: ${error.message}`)
    }
  } finally {
    resuming.value = false
  }
}

async function loadRiskControl() {
  loadingRisk.value = true
  try {
    const data = await systemApi.getRiskControlStatus()
    Object.assign(riskControlStatus, data)
    riskForm.max_daily_orders = data.max_daily_orders
    riskForm.max_daily_cancels = data.max_daily_cancels
    riskForm.max_order_volume = data.max_order_volume
    riskForm.max_split_volume = data.max_split_volume
    riskForm.order_timeout = data.order_timeout
  } catch (error: any) {
    ElMessage.error(`加载风控参数失败: ${error.message}`)
  } finally {
    loadingRisk.value = false
  }
}

async function updateRiskControl() {
  updatingRisk.value = true
  try {
    const result = await systemApi.updateRiskControl(
      riskForm.max_daily_orders,
      riskForm.max_daily_cancels,
      riskForm.max_order_volume,
      riskForm.max_split_volume,
      riskForm.order_timeout
    )
    console.log('更新风控参数成功:', result)
    Object.assign(riskControlStatus, result)
    riskForm.max_daily_orders = result.max_daily_orders
    riskForm.max_daily_cancels = result.max_daily_cancels
    riskForm.max_order_volume = result.max_order_volume
    riskForm.max_split_volume = result.max_split_volume
    riskForm.order_timeout = result.order_timeout
    ElMessage.success('风控参数已更新')
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
    const result = await systemApi.getScheduledTasks()
    tasks.value = result.tasks
  } catch (error: any) {
    ElMessage.error(`加载定时任务失败: ${error.message}`)
  } finally {
    loadingTasks.value = false
  }
}

// @ts-expect-error - kept for future use
async function handleToggleTask(row: Job) {
  try {
    await jobsApi.toggleJob(row.job_id, row.enabled)
    ElMessage.success('更新成功')
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
    row.enabled = !row.enabled
  }
}

async function handleOperateJob(row: Job, action: 'pause' | 'resume' | 'trigger') {
  const actionKey = `${row.job_id}_${action}`
  operatingJob.value = actionKey
  try {
    await jobsApi.operateJob(row.job_id, action)
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
  loadRiskControl()
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
