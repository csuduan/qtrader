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

          <el-form label-width="160px">
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="即时告警">
                  <el-switch
                    v-model="alertConfig.immediate"
                    active-text="开启"
                    inactive-text="关闭"
                  />
                  <div class="form-help">Trader异常、连接断开等立即发送告警</div>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="阈值告警">
                  <el-switch
                    v-model="alertConfig.threshold"
                    active-text="开启"
                    inactive-text="关闭"
                  />
                  <div class="form-help">异常日志达到阈值时发送告警</div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="阈值告警数量">
                  <el-input-number
                    v-model="alertConfig.threshold_count"
                    :min="1"
                    :max="100"
                    :disabled="!alertConfig.threshold"
                  />
                  <span class="ml-2">次</span>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="阈值时间窗口">
                  <el-input-number
                    v-model="alertConfig.threshold_window"
                    :min="60"
                    :max="3600"
                    :step="60"
                    :disabled="!alertConfig.threshold"
                  />
                  <span class="ml-2">秒</span>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :xs="24" :sm="12">
                <el-form-item label="免打扰开始时间">
                  <el-input-number
                    v-model="alertConfig.dnd_start"
                    :min="0"
                    :max="23"
                  />
                  <span class="ml-2">点</span>
                  <div class="form-help">此时间段内不发送即时告警（默认23点）</div>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="免打扰结束时间">
                  <el-input-number
                    v-model="alertConfig.dnd_end"
                    :min="0"
                    :max="23"
                  />
                  <span class="ml-2">点</span>
                  <div class="form-help">免打扰结束时间（默认次日8点）</div>
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
              <div class="header-actions">
                <el-space>
                  <template v-if="traderList.length > 0">
                    <el-button
                      type="success"
                      :disabled="selectedStoppedTraders.length === 0"
                      @click="handleBatchStart"
                      :loading="batchStarting"
                    >
                      <el-icon><VideoPlay /></el-icon>
                      启动 ({{ selectedStoppedTraders.length }})
                    </el-button>
                    <el-button
                      type="danger"
                      :disabled="selectedRunningTraders.length === 0"
                      @click="handleBatchStop"
                      :loading="batchStopping"
                    >
                      <el-icon><VideoPause /></el-icon>
                      停止 ({{ selectedRunningTraders.length }})
                    </el-button>
                    <el-divider direction="vertical" />
                  </template>
                  <el-button type="primary" @click="loadTradersStatus" :loading="loadingTraders">
                    <el-icon><Refresh /></el-icon>
                    刷新
                  </el-button>
                </el-space>
              </div>
            </div>
          </template>

          <div class="table-wrapper">
            <el-table
              :data="traderList"
              v-loading="loadingTraders"
              stripe
              ref="tableRef"
              @selection-change="handleSelectionChange"
            >
              <el-table-column type="selection" width="55" />
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
          </div>
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

          <div class="table-wrapper">
            <el-table :data="jobList" stripe v-loading="loadingJobs" table-layout="fixed">
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
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, computed } from 'vue'
import { ElMessage, ElSpace } from 'element-plus'
import { VideoPlay, VideoPause, Refresh, Check } from '@element-plus/icons-vue'
import { systemApi, accountApi } from '@/api'
import type { TraderStatus, Job } from '@/types'

// ==================== 告警设置（Manager级别）====================
const savingAlert = ref(false)
const alertConfig = reactive({
  immediate: true,
  threshold: true,
  threshold_count: 5,
  threshold_window: 300,
  dnd_start: 23,
  dnd_end: 8
})

async function loadAlertConfig() {
  try {
    const res = await systemApi.getManagerAlertConfig()
    alertConfig.immediate = res.immediate
    alertConfig.threshold = res.threshold
    alertConfig.threshold_count = res.threshold_count ?? 5
    alertConfig.threshold_window = res.threshold_window ?? 300
    alertConfig.dnd_start = res.dnd_start ?? 23
    alertConfig.dnd_end = res.dnd_end ?? 8
  } catch (error: any) {
    ElMessage.error(`加载告警配置失败: ${error.message}`)
  }
}

async function saveAlertConfig() {
  savingAlert.value = true
  try {
    await systemApi.updateManagerAlertConfig({
      immediate: alertConfig.immediate,
      threshold: alertConfig.threshold,
      threshold_count: alertConfig.threshold_count,
      threshold_window: alertConfig.threshold_window,
      dnd_start: alertConfig.dnd_start,
      dnd_end: alertConfig.dnd_end
    })
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

// 表格引用
const tableRef = ref<any>(null)
const batchStarting = ref(false)
const batchStopping = ref(false)

// 当前选中的行
const selectedRows = ref<TraderStatus[]>([])

// 计算选中的已停止账户（可启动）
const selectedStoppedTraders = computed(() => {
  return selectedRows.value.filter(t => !t.running)
})

// 计算选中的运行中账户（可停止）
const selectedRunningTraders = computed(() => {
  return selectedRows.value.filter(t => t.running)
})

// 处理选择变化
function handleSelectionChange(selection: TraderStatus[]) {
  selectedRows.value = selection
}

// 批量启动
async function handleBatchStart() {
  const traders = selectedStoppedTraders.value
  if (traders.length === 0) {
    ElMessage.warning('没有可启动的账户')
    return
  }

  batchStarting.value = true
  const results: { success: string[]; failed: string[] } = { success: [], failed: [] }

  try {
    for (const trader of traders) {
      try {
        await accountApi.startTrader(trader.account_id)
        results.success.push(trader.account_id)
      } catch (error: any) {
        results.failed.push(trader.account_id)
        console.error(`启动账户 ${trader.account_id} 失败:`, error)
      }
    }

    if (results.success.length > 0) {
      ElMessage.success(`成功启动 ${results.success.length} 个账户`)
    }
    if (results.failed.length > 0) {
      ElMessage.error(`${results.failed.length} 个账户启动失败`)
    }

    await loadTradersStatus()
  } finally {
    batchStarting.value = false
  }
}

// 批量停止
async function handleBatchStop() {
  const traders = selectedRunningTraders.value
  if (traders.length === 0) {
    ElMessage.warning('没有可停止的账户')
    return
  }

  batchStopping.value = true
  const results: { success: string[]; failed: string[] } = { success: [], failed: [] }

  try {
    for (const trader of traders) {
      try {
        await accountApi.stopTrader(trader.account_id)
        results.success.push(trader.account_id)
      } catch (error: any) {
        results.failed.push(trader.account_id)
        console.error(`停止账户 ${trader.account_id} 失败:`, error)
      }
    }

    if (results.success.length > 0) {
      ElMessage.success(`成功停止 ${results.success.length} 个账户`)
    }
    if (results.failed.length > 0) {
      ElMessage.error(`${results.failed.length} 个账户停止失败`)
    }

    await loadTradersStatus()
  } finally {
    batchStopping.value = false
  }
}

async function loadTradersStatus() {
  loadingTraders.value = true
  try {
    traderList.value = await accountApi.getTradersStatus()
    // 清空表格选择
    selectedRows.value = []
    if (tableRef.value) {
      tableRef.value.clearSelection()
    }
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
  gap: 10px;
  flex-wrap: wrap;
}

.table-wrapper {
  width: 100%;
  overflow-x: auto;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.form-help {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
}

.header-actions {
  display: flex;
  align-items: center;
}
</style>
