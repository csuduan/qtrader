<template>
  <div class="system-admin">
    <el-row :gutter="20">
      <!-- 告警设置 -->
      <el-col :span="24">
        <el-card shadow="hover" class="mt-4">
          <template #header>
            <div class="card-header">
              <span>告警设置</span>
              <el-button type="primary" @click="saveAlertConfig" :loading="savingAlert">
                <el-icon><Check /></el-icon>
                保存配置
              </el-button>
            </div>
          </template>

          <el-form label-width="140px">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="即时告警">
                  <el-switch
                    v-model="alertConfig.immediate"
                    active-text="开启"
                    inactive-text="关闭"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="异常告警">
                  <el-switch
                    v-model="alertConfig.threshold"
                    active-text="开启"
                    inactive-text="关闭"
                  />
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <!-- 账户实例列表 -->
    <el-row :gutter="20" class="mt-4">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>账户实例</span>
              <el-button type="primary" @click="loadTradersStatus" :loading="loadingTraders">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </template>

          <el-table :data="traderList" v-loading="loadingTraders" stripe>
            <el-table-column prop="account_id" label="账户ID" min-width="120" />
            <el-table-column prop="state" label="状态" min-width="100">
              <template #default="{ row }">
                <el-tag :type="getStateTagType(row.state)" size="small">
                  {{ getStateLabel(row.state) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="pid" label="PID" min-width="100">
              <template #default="{ row }">
                <span>{{ row.pid ?? '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="start_time" label="启动时间" min-width="180">
              <template #default="{ row }">
                <span>{{ formatDateTime(row.start_time) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="220" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="!row.running"
                  type="success"
                  size="small"
                  @click="handleStart(row.account_id)"
                  :loading="actionLoading[row.account_id]"
                >
                  启动
                </el-button>
                <el-button
                  v-if="row.running"
                  type="danger"
                  size="small"
                  @click="handleStop(row.account_id)"
                  :loading="actionLoading[row.account_id]"
                >
                  停止
                </el-button>
                <el-button
                  type="primary"
                  size="small"
                  @click="handleRestart(row.account_id)"
                  :loading="actionLoading[row.account_id]"
                >
                  重启
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 定时任务列表 -->
    <el-row :gutter="20" class="mt-4">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>定时任务</span>
              <el-button type="primary" @click="loadJobs" :loading="loadingJobs">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </template>

          <el-table :data="jobList" stripe v-loading="loadingJobs" height="300" table-layout="fixed">
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
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { ElMessage, ElSpace } from 'element-plus'
import { useStore } from '@/stores'
import { systemApi, accountApi } from '@/api'
import type { TraderStatus, Job } from '@/types'

const store = useStore()

// ==================== 告警设置 ====================
const savingAlert = ref(false)
const alertConfig = reactive({
  immediate: true,
  threshold: true,
  threshold_count: 5,
  threshold_window: 300
})

async function loadAlertConfig() {
  const accountId = store.currentAccount?.account_id
  if (!accountId) {
    return
  }
  try {
    const res = await systemApi.getAlertConfig(accountId)
    alertConfig.immediate = res.immediate
    alertConfig.threshold = res.threshold
    alertConfig.threshold_count = res.threshold_count ?? 5
    alertConfig.threshold_window = res.threshold_window ?? 300
  } catch (error: any) {
    ElMessage.error(`加载告警配置失败: ${error.message}`)
  }
}

async function saveAlertConfig() {
  const accountId = store.currentAccount?.account_id
  if (!accountId) {
    ElMessage.warning('请先选择账户')
    return
  }
  savingAlert.value = true
  try {
    await systemApi.updateAlertConfig(
      {
        immediate: alertConfig.immediate,
        threshold: alertConfig.threshold,
        threshold_count: alertConfig.threshold_count,
        threshold_window: alertConfig.threshold_window
      },
      accountId
    )
    ElMessage.success('告警配置已保存')
  } catch (error: any) {
    ElMessage.error(`保存告警配置失败: ${error.message}`)
  } finally {
    savingAlert.value = false
  }
}

// ==================== 账户实例列表 ====================
const loadingTraders = ref(false)
const traderList = ref<TraderStatus[]>([])
const actionLoading = reactive<Record<string, boolean>>({})

async function loadTradersStatus() {
  loadingTraders.value = true
  try {
    traderList.value = await accountApi.getTradersStatus()
  } catch (error: any) {
    ElMessage.error(`加载账户实例列表失败: ${error.message}`)
  } finally {
    loadingTraders.value = false
  }
}

function getStateTagType(state: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  switch (state) {
    case 'connected':
      return 'success'
    case 'connecting':
      return 'warning'
    case 'stopped':
      return 'danger'
    default:
      return 'info'
  }
}

function getStateLabel(state: string): string {
  switch (state) {
    case 'connected':
      return '已连接'
    case 'connecting':
      return '连接中'
    case 'stopped':
      return '已停止'
    default:
      return state
  }
}

function formatDateTime(dt: string | number | null | undefined): string {
  if (!dt) return '-'
  const d = typeof dt === 'number' ? new Date(dt * 1000) : new Date(dt)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString('zh-CN')
}

async function handleStart(accountId: string) {
  actionLoading[accountId] = true
  try {
    await accountApi.startTrader(accountId)
    ElMessage.success(`账户 ${accountId} 已启动`)
    await loadTradersStatus()
  } catch (error: any) {
    ElMessage.error(`启动失败: ${error.message}`)
  } finally {
    actionLoading[accountId] = false
  }
}

async function handleStop(accountId: string) {
  actionLoading[accountId] = true
  try {
    await accountApi.stopTrader(accountId)
    ElMessage.success(`账户 ${accountId} 已停止`)
    await loadTradersStatus()
  } catch (error: any) {
    ElMessage.error(`停止失败: ${error.message}`)
  } finally {
    actionLoading[accountId] = false
  }
}

async function handleRestart(accountId: string) {
  actionLoading[accountId] = true
  try {
    await accountApi.restartTrader(accountId)
    ElMessage.success(`账户 ${accountId} 已重启`)
    await loadTradersStatus()
  } catch (error: any) {
    ElMessage.error(`重启失败: ${error.message}`)
  } finally {
    actionLoading[accountId] = false
  }
}

// ==================== 定时任务列表（Manager级别） ====================
const loadingJobs = ref(false)
const jobList = ref<Job[]>([])
const operatingJob = ref<string | null>(null)

async function loadJobs() {
  loadingJobs.value = true
  try {
    const res = await systemApi.getManagerSchedulerJobs()
    jobList.value = res.tasks || []
  } catch (error: any) {
    ElMessage.error(`加载定时任务失败: ${error.message}`)
  } finally {
    loadingJobs.value = false
  }
}

async function handleOperateJob(row: Job, action: 'pause' | 'resume' | 'trigger') {
  const actionKey = `${row.job_id}_${action}`
  operatingJob.value = actionKey
  try {
    await systemApi.operateManagerSchedulerJob(row.job_id, action)
    const actionText = action === 'pause' ? '暂停' : action === 'resume' ? '恢复' : '触发'
    ElMessage.success(`任务 ${row.job_name} 已${actionText}`)
    if (action === 'pause') {
      row.enabled = false
    } else if (action === 'resume') {
      row.enabled = true
    }
    await loadJobs()
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  } finally {
    operatingJob.value = null
  }
}

onMounted(() => {
  loadAlertConfig()
  loadTradersStatus()
  loadJobs()
})
</script>

<style scoped>
.system-admin {
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

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
