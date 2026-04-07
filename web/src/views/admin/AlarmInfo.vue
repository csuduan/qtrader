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

      <div ref="chartRef" class="resource-chart" />
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
        <el-table :data="alarms" stripe v-loading="loading" table-layout="fixed" empty-text="暂无告警信息">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="alarm_time" label="时间" width="100" />
          <el-table-column prop="source" label="来源" width="100" />
          <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
          <el-table-column prop="detail" label="详情" min-width="300" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status)">
                {{ getStatusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'UNCONFIRMED'"
                type="primary"
                size="small"
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
import type { Alarm, AlarmStats, AlarmStatus, ResourceSnapshot, ResourcePoint } from '@/types'
import * as echarts from 'echarts'

const store = useStore()

// ==================== 资源监控 ====================
const monitorLoading = ref(false)
const currentSnapshot = ref<ResourceSnapshot | null>(null)
const historyPoints = ref<ResourcePoint[]>([])
const chartRef = ref<HTMLDivElement | null>(null)
let chartInstance: echarts.ECharts | null = null
let monitorTimer: number | null = null

async function loadResourceCurrent() {
  try {
    const res = await resourceApi.getResourceCurrent()
    currentSnapshot.value = res
    if (res) {
      const point: ResourcePoint = {
        timestamp: res.timestamp,
        cpu_percent: res.cpu_percent,
        memory_percent: res.memory_percent,
        memory_used_gb: res.memory_used_gb,
        memory_total_gb: res.memory_total_gb,
        disk_percent: res.disk_percent,
        disk_used_gb: res.disk_used_gb,
        disk_total_gb: res.disk_total_gb
      }
      historyPoints.value.push(point)
      if (historyPoints.value.length > 120) {
        historyPoints.value.shift()
      }
      updateChart()
    }
  } catch (error: any) {
    console.error(`加载资源监控失败: ${error.message}`)
  }
}

async function loadResourceHistory() {
  monitorLoading.value = true
  try {
    const res = await resourceApi.getResourceHistory(60)
    historyPoints.value = res.points || []
    updateChart()
  } catch (error: any) {
    ElMessage.error(`加载资源历史数据失败: ${error.message}`)
  } finally {
    monitorLoading.value = false
  }
}

function initChart() {
  if (!chartRef.value) return
  chartInstance = echarts.init(chartRef.value)
  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis'
    },
    legend: {
      data: ['CPU (%)', '内存 (%)'],
      bottom: 0
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '15%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: []
    },
    yAxis: {
      type: 'value',
      name: '使用率 (%)',
      max: 100,
      axisLabel: { formatter: '{value} %' }
    },
    series: [
      {
        name: 'CPU (%)',
        type: 'line',
        smooth: true,
        data: [],
        itemStyle: { color: '#409eff' }
      },
      {
        name: '内存 (%)',
        type: 'line',
        smooth: true,
        data: [],
        itemStyle: { color: '#67c23a' }
      }
    ]
  }
  chartInstance.setOption(option)
  window.addEventListener('resize', handleResize)
}

function updateChart() {
  if (!chartInstance || historyPoints.value.length === 0) return
  const labels = historyPoints.value.map(p => {
    const d = new Date(p.timestamp)
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`
  })
  const cpuData = historyPoints.value.map(p => p.cpu_percent)
  const memData = historyPoints.value.map(p => p.memory_percent)

  chartInstance.setOption({
    xAxis: { data: labels },
    series: [
      { data: cpuData },
      { data: memData }
    ]
  })
}

function handleResize() {
  chartInstance?.resize()
}

async function refreshMonitor() {
  await loadResourceHistory()
  await loadResourceCurrent()
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

onMounted(async () => {
  // 监控
  await loadResourceHistory()
  await loadResourceCurrent()
  initChart()
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
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.alarm-info {
  height: 100%;
}

.monitor-card {
  margin-bottom: 16px;
}

.resource-chart {
  width: 100%;
  height: 280px;
}

@media (max-width: 768px) {
  .resource-chart {
    height: 220px;
  }
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
