<template>
  <div class="alarm-info">
    <!-- 服务器资源监控 -->
    <el-card shadow="hover" class="monitor-card">
      <template #header>
        <div class="card-header">
          <span>服务器资源监控</span>
          <el-button @click="refreshMonitor" :loading="monitorLoading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-row :gutter="20" class="mb-4">
        <el-col :xs="24" :sm="8">
          <el-statistic title="CPU 使用率" :value="currentSnapshot?.cpu_percent ?? 0">
            <template #suffix>%</template>
          </el-statistic>
        </el-col>
        <el-col :xs="24" :sm="8">
          <div class="stat-card">
            <div class="stat-title">内存使用</div>
            <div class="stat-complex">
              <span class="stat-main">{{ currentSnapshot?.memory_used_gb ?? 0 }} / {{ currentSnapshot?.memory_total_gb ?? 0 }} GB</span>
              <span class="stat-sub">({{ currentSnapshot?.memory_percent ?? 0 }}%)</span>
            </div>
          </div>
        </el-col>
        <el-col :xs="24" :sm="8">
          <div class="stat-card">
            <div class="stat-title">磁盘使用</div>
            <div class="stat-complex">
              <span class="stat-main">{{ currentSnapshot?.disk_used_gb ?? 0 }} / {{ currentSnapshot?.disk_total_gb ?? 0 }} GB</span>
              <span class="stat-sub">({{ currentSnapshot?.disk_percent ?? 0 }}%)</span>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 告警信息 -->
    <el-card shadow="hover" class="mt-4">
      <template #header>
        <div class="card-header">
          <span>告警信息</span>
          <el-button @click="loadAlarms" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <!-- 账户筛选 -->
      <el-row :gutter="20" class="mb-4">
        <el-col :span="24">
          <div class="filter-bar">
            <span style="font-size: 14px;">账户筛选:</span>
            <el-select
              v-model="selectedAccountId"
              placeholder="全部账户"
              clearable
              style="width: 200px"
              @change="handleAccountFilterChange"
            >
              <el-option
                v-for="acc in store.accounts"
                :key="acc.account_id"
                :label="acc.account_id"
                :value="acc.account_id"
              />
            </el-select>
          </div>
        </el-col>
      </el-row>

      <el-row :gutter="20" class="mb-4">
        <el-col :xs="12" :sm="6">
          <el-statistic title="今日总告警数" :value="stats.today_total">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-statistic title="未处理告警数" :value="stats.unconfirmed">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-statistic title="近1小时告警数" :value="stats.last_hour">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-statistic title="近5分钟告警数" :value="stats.last_five_minutes">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
      </el-row>

      <el-row :gutter="20" class="mb-4" align="middle">
        <el-col :xs="24" :sm="18">
          <div class="filter-bar">
            <span style="font-size: 14px;">告警状态:</span>
            <el-radio-group v-model="statusFilter" @change="handleFilterChange" size="small">
              <el-radio-button value="UNCONFIRMED">未处理</el-radio-button>
              <el-radio-button value="CONFIRMED">已处理</el-radio-button>
            </el-radio-group>
          </div>
        </el-col>
        <el-col :xs="24" :sm="6" style="text-align: right;">
          <el-button
            type="primary"
            @click="handleConfirmAll"
            :loading="confirmingAll"
            :disabled="!hasUnconfirmedAlarms"
          >
            全部标记已处理
          </el-button>
        </el-col>
      </el-row>

      <div class="table-wrapper">
        <el-table :data="alarms" stripe v-loading="loading" table-layout="fixed" empty-text="暂无告警信息" :size="isMobile ? 'small' : 'default'">
          <el-table-column prop="id" label="ID" :width="isMobile ? 60 : 80" />
          <el-table-column prop="alarm_time" label="时间" :width="isMobile ? 80 : 100" />
          <el-table-column v-if="!isMobile" prop="source" label="来源" width="100" />
          <el-table-column prop="title" label="标题" :min-width="isMobile ? 120 : 200" show-overflow-tooltip />
          <el-table-column v-if="!isMobile" prop="detail" label="详情" min-width="300" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" :width="isMobile ? 70 : 120">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status)" size="small">
                {{ getStatusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 90 : 120">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'UNCONFIRMED'"
                type="primary"
                :size="isMobile ? 'small' : 'default'"
                @click="handleConfirm(row.id)"
                :loading="confirmingId === row.id"
              >
                标记已处理
              </el-button>
              <span v-else class="text-gray">已处理</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { alarmApi, resourceApi } from '@/api'
import { useStore } from '@/stores'
import type { Alarm, AlarmStats, AlarmStatus, ResourceSnapshot } from '@/types'

const store = useStore()

// ==================== 资源监控 ====================
const monitorLoading = ref(false)
const currentSnapshot = ref<ResourceSnapshot | null>(null)
let monitorTimer: number | null = null

async function loadResourceCurrent() {
  try {
    currentSnapshot.value = await resourceApi.getResourceCurrent()
  } catch (error: any) {
    console.error(`加载资源监控失败: ${error.message}`)
  }
}

async function refreshMonitor() {
  monitorLoading.value = true
  try {
    await loadResourceCurrent()
  } finally {
    monitorLoading.value = false
  }
}

// ==================== 告警信息（原有逻辑） ====================
const alarms = ref<Alarm[]>([])
const stats = ref<AlarmStats>({
  today_total: 0,
  unconfirmed: 0,
  last_hour: 0,
  last_five_minutes: 0
})
const loading = ref(false)
const confirmingId = ref<number | null>(null)
const confirmingAll = ref(false)
const statusFilter = ref<AlarmStatus | ''>('UNCONFIRMED')
const statsTimer = ref<number | null>(null)
const selectedAccountId = ref<string | null>(null)

const hasUnconfirmedAlarms = computed(() => {
  return alarms.value.some(a => a.status === 'UNCONFIRMED')
})

async function loadAlarms() {
  loading.value = true
  try {
    alarms.value = await alarmApi.getTodayAlarms(statusFilter.value || undefined, selectedAccountId.value || undefined)
  } catch (error: any) {
    ElMessage.error(`加载告警列表失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await alarmApi.getAlarmStats(selectedAccountId.value || undefined)
  } catch (error: any) {
    console.error(`加载告警统计失败: ${error.message}`)
  }
}

function handleFilterChange() {
  loadAlarms()
}

function handleAccountFilterChange() {
  loadAlarms()
  loadStats()
}

async function handleConfirm(alarmId: number) {
  confirmingId.value = alarmId
  try {
    await alarmApi.confirmAlarm(alarmId)
    ElMessage.success('标记成功')
    await loadAlarms()
    await loadStats()
  } catch (error: any) {
    ElMessage.error(`标记失败: ${error.message}`)
  } finally {
    confirmingId.value = null
  }
}

async function handleConfirmAll() {
  confirmingAll.value = true
  try {
    const result = await alarmApi.confirmAllAlarms(selectedAccountId.value || undefined)
    ElMessage.success(`已标记 ${result.confirmed_count} 条告警为已处理`)
    await loadAlarms()
    await loadStats()
  } catch (error: any) {
    ElMessage.error(`批量标记失败: ${error.message}`)
  } finally {
    confirmingAll.value = false
  }
}

function getStatusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  const types: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
    'UNCONFIRMED': 'danger',
    'CONFIRMED': 'success'
  }
  return types[status] ?? 'info'
}

function getStatusText(status: string): string {
  const texts: Record<string, string> = {
    'UNCONFIRMED': '未处理',
    'CONFIRMED': '已处理'
  }
  return texts[status] ?? status
}

const isMobile = ref(false)
const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 768
}

onMounted(async () => {
  updateIsMobile()
  window.addEventListener('resize', updateIsMobile)
  // 监控
  await loadResourceCurrent()
  monitorTimer = window.setInterval(() => {
    loadResourceCurrent()
  }, 5000)

  // 告警
  await loadAlarms()
  await loadStats()
  statsTimer.value = window.setInterval(() => {
    loadStats()
  }, 30000)
})

onUnmounted(() => {
  if (monitorTimer) {
    clearInterval(monitorTimer)
    monitorTimer = null
  }
  if (statsTimer.value) {
    clearInterval(statsTimer.value)
    statsTimer.value = null
  }
  window.removeEventListener('resize', updateIsMobile)
})
</script>

<style scoped>
.alarm-info {
  height: 100%;
}

.monitor-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.mb-4 {
  margin-bottom: 16px;
}

.text-gray {
  color: #909399;
  font-size: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.stat-title {
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}

.stat-complex {
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}

.stat-main {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.stat-sub {
  font-size: 12px;
  color: #909399;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.table-wrapper {
  width: 100%;
  overflow-x: auto;
}
</style>
