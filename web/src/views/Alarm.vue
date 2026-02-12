<template>
  <div class="alarm">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>告警管理</span>
          <el-button @click="loadAlarms" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-row :gutter="20" class="mb-4">
        <el-col :span="6">
          <el-statistic title="今日总告警数" :value="stats.today_total">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="未处理告警数" :value="stats.unconfirmed">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="近1小时告警数" :value="stats.last_hour">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="近5分钟告警数" :value="stats.last_five_minutes">
            <template #suffix>条</template>
          </el-statistic>
        </el-col>
      </el-row>

      <el-row :gutter="20" class="mb-4">
        <el-col :span="18">
          <div style="display: flex; align-items: center;">
            <span style="margin-right: 12px; font-size: 14px;">告警状态:</span>
            <el-radio-group v-model="statusFilter" @change="handleFilterChange" size="small">
              <el-radio-button value="UNCONFIRMED">未处理</el-radio-button>
              <el-radio-button value="CONFIRMED">已处理</el-radio-button>
            </el-radio-group>
          </div>
        </el-col>
        <el-col :span="6" style="text-align: right;">
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
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { alarmApi } from '@/api'
import type { Alarm, AlarmStats, AlarmStatus } from '@/types'

const store = useStore()

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

// 是否有未处理的告警
const hasUnconfirmedAlarms = computed(() => {
  return alarms.value.some(a => a.status === 'UNCONFIRMED')
})

async function loadAlarms() {
  loading.value = true
  try {
    alarms.value = await alarmApi.getTodayAlarms(store.selectedAccountId || undefined, statusFilter.value || undefined)
  } catch (error: any) {
    ElMessage.error(`加载告警列表失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await alarmApi.getAlarmStats(store.selectedAccountId || undefined)
  } catch (error: any) {
    console.error(`加载告警统计失败: ${error.message}`)
  }
}

function handleFilterChange() {
  loadAlarms()
}

async function handleConfirm(alarmId: number) {
  confirmingId.value = alarmId
  try {
    await alarmApi.confirmAlarm(alarmId, store.selectedAccountId || undefined)
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
    const result = await alarmApi.confirmAllAlarms(store.selectedAccountId || undefined)
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

// 监听账户切换，重新加载数据
watch(() => store.selectedAccountId, async (newId) => {
  if (newId) {
    await loadAlarms()
    await loadStats()
  }
})

onMounted(async () => {
  await loadAlarms()
  await loadStats()

  statsTimer.value = window.setInterval(() => {
    loadStats()
  }, 30000)
})
</script>

<style scoped>
.alarm {
  height: 100%;
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
</style>
