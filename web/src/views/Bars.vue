<template>
  <div class="bars-page">
    <el-form :inline="true">
      <el-form-item label="合约">
        <el-input v-model="form.symbol" placeholder="如 IM2609" style="width: 140px" clearable />
      </el-form-item>
      <el-form-item label="周期">
        <el-select v-model="form.interval" style="width: 100px">
          <el-option v-for="iv in intervals" :key="iv" :label="iv" :value="iv" />
        </el-select>
      </el-form-item>
      <el-form-item label="时间范围">
        <el-date-picker
          v-model="dateRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          style="width: 320px"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="loadBars">查询</el-button>
        <el-radio-group v-model="viewMode" class="view-toggle">
          <el-radio-button value="table">表格</el-radio-button>
          <el-radio-button value="chart">K线图</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item>
        <el-tag :type="feedStatus?.connected ? 'success' : 'danger'" size="small">
          数据服务{{ feedStatus?.connected ? '已连接' : '未连接' }}
        </el-tag>
        <el-button size="small" :loading="syncing" class="sync-btn" @click="handleSync">
          同步
        </el-button>
      </el-form-item>
    </el-form>

    <!-- 表格视图（默认） -->
    <el-table
      v-if="viewMode === 'table'"
      :data="bars"
      v-loading="loading"
      stripe
      size="small"
      max-height="560"
      class="bars-table"
    >
      <el-table-column prop="datetime" label="时间" width="160">
        <template #default="{ row }">{{ row.datetime.slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column prop="open" label="开" align="right" />
      <el-table-column prop="high" label="高" align="right" />
      <el-table-column prop="low" label="低" align="right" />
      <el-table-column prop="close" label="收" align="right" />
      <el-table-column prop="volume" label="成交量" align="right" />
      <el-table-column prop="source" label="来源" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source === 'MANAGER' ? 'success' : 'info'">
            {{ row.source }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <!-- K线图视图 -->
    <div v-show="viewMode === 'chart'" ref="chartRef" class="chart-container" v-loading="loading" />
    <div class="chart-footer">
      共 {{ bars.length }} 根K线
      <span v-if="bars.length" class="time-range">
        {{ bars[0]?.datetime.slice(0, 16) }} ~
        {{ bars[bars.length - 1]?.datetime.slice(0, 16) }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { barsApi, type BarItem, type BarFeedStatus } from '@/api/bars'

const intervals = ['M1', 'M5', 'M15', 'M30', 'H1']

const form = ref({ symbol: '', interval: 'M1' })
const dateRange = ref<[Date, Date]>(getDefaultRange())
const bars = ref<BarItem[]>([])
const loading = ref(false)
const syncing = ref(false)
const feedStatus = ref<BarFeedStatus | null>(null)
const viewMode = ref<'table' | 'chart'>('table')

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

// 切换到K线图时，容器从隐藏变为可见需要重新渲染并resize
watch(viewMode, async (mode) => {
  if (mode === 'chart') {
    await nextTick()
    renderChart()
    chartInstance?.resize()
  }
})

function getDefaultRange(): [Date, Date] {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - 1)
  return [start, end]
}

async function loadBars() {
  if (!form.value.symbol) {
    ElMessage.warning('请输入合约代码')
    return
  }
  loading.value = true
  try {
    const data = await barsApi.getBars({
      symbol: form.value.symbol.trim(),
      interval: form.value.interval,
      start: dateRange.value[0].toISOString(),
      end: dateRange.value[1].toISOString(),
      limit: 2000,
    })
    bars.value = data
    renderChart()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '查询失败')
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }

  const data = bars.value
  const times = data.map((b) => b.datetime.slice(0, 16))
  const klineData = data.map((b) => [b.open, b.close, b.low, b.high])
  const volumes = data.map((b) => b.volume)

  const option: echarts.EChartsOption = {
    animation: false,
    legend: { data: ['K线', '成交量'] },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: [
      { left: 60, right: 20, top: 30, height: '62%' },
      { left: 60, right: 20, top: '74%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: times,
        gridIndex: 0,
        axisLabel: { show: false },
      },
      { type: 'category', data: times, gridIndex: 1 },
    ],
    yAxis: [
      { scale: true, gridIndex: 0 },
      { scale: true, gridIndex: 1 },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1] },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 4 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: klineData,
        itemStyle: {
          color: '#ec0000',
          color0: '#00da3c',
          borderColor: '#8A0000',
          borderColor0: '#008F28',
        },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: { color: '#7fbe9e' },
      },
    ],
  }
  chartInstance.setOption(option, true)
}

async function handleSync() {
  syncing.value = true
  try {
    const result = await barsApi.syncBars()
    ElMessage.success(result.message || '同步已触发')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '同步失败')
  } finally {
    syncing.value = false
  }
}

async function loadFeedStatus() {
  try {
    feedStatus.value = await barsApi.getFeedStatus()
  } catch {
    feedStatus.value = null
  }
}

function handleResize() {
  chartInstance?.resize()
}

onMounted(() => {
  loadFeedStatus()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.bars-page {
  padding: 0;
}

.view-toggle {
  margin-left: 12px;
}

.sync-btn {
  margin-left: 8px;
}

.bars-table {
  width: 100%;
}

.chart-container {
  width: 100%;
  height: 520px;
}

.chart-footer {
  margin-top: 8px;
  color: #909399;
  font-size: 12px;
}

.time-range {
  margin-left: 12px;
}
</style>
