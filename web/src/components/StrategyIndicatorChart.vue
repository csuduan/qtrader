<template>
  <el-card shadow="hover" class="indicator-card">
    <template #header>
      <div class="card-header">
        <span>
          指标走势
          <template v-if="data">（{{ data.trading_day }} {{ data.symbol }}）</template>
        </span>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </template>

    <el-empty
      v-if="!loading && !hasData"
      description="暂无指标数据（策略未初始化、非RSI策略或当日无行情）"
      :image-size="60"
    />
    <template v-else>
      <!-- 高波模式判定信息 -->
      <el-descriptions
        v-if="data && data.mode === 1"
        :column="isMobile ? 2 : 5"
        border
        size="small"
        class="hv-desc"
      >
        <el-descriptions-item label="昨收">{{ fmtPrice(data.hv?.prev_close) }}</el-descriptions-item>
        <el-descriptions-item label="今开">{{ fmtPrice(data.hv?.day_open) }}</el-descriptions-item>
        <el-descriptions-item label="09:45收盘">{{ fmtPrice(data.hv?.close_0945) }}</el-descriptions-item>
        <el-descriptions-item label="前15分钟涨跌">{{ fmtPct(data.hv?.abs_ret15) }}</el-descriptions-item>
        <el-descriptions-item label="判定">
          <el-tag v-if="data.hv?.side === 1" type="danger" size="small">做多</el-tag>
          <el-tag v-else-if="data.hv?.side === -1" type="primary" size="small">做空</el-tag>
          <el-tag v-else type="info" size="small">{{ data.hv?.decided ? '空仓' : '未判定' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item v-if="data.hv?.reason" label="判定依据" :span="isMobile ? 2 : 5">
          {{ data.hv.reason }}
        </el-descriptions-item>
      </el-descriptions>

      <!-- 普通RSI模式信号信息 -->
      <el-descriptions
        v-if="data && data.mode === 0 && entryEvent"
        :column="isMobile ? 1 : 3"
        border
        size="small"
        class="hv-desc"
      >
        <el-descriptions-item label="开仓">
          {{ entryEvent.time }} {{ entryEvent.side === 1 ? '开多' : '开空' }} @
          {{ entryEvent.price.toFixed(2) }}
        </el-descriptions-item>
        <el-descriptions-item label="信号依据" :span="isMobile ? 1 : exitEvent ? 1 : 2">
          {{ entryEvent.reason || '-' }}
        </el-descriptions-item>
        <el-descriptions-item v-if="exitEvent" label="平仓">
          {{ exitEvent.time }} {{ REASON_TEXT[exitEvent.reason] || '平仓' }} @
          {{ exitEvent.price.toFixed(2) }}
        </el-descriptions-item>
      </el-descriptions>
      <div
        v-show="hasData"
        ref="chartRef"
        class="chart-container"
        v-loading="loading"
      />
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { strategyApi } from '@/api'
import type { StrategyIndicators } from '@/types'

const props = defineProps<{ strategyId: string }>()
const store = useStore()

const data = ref<StrategyIndicators | null>(null)
const loading = ref(false)
const isMobile = ref(window.innerWidth <= 768)

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const hasData = computed(() => !!data.value && data.value.bars.length > 0)
const entryEvent = computed(() => data.value?.events.find((e) => e.type === 'ENTRY'))
const exitEvent = computed(() => data.value?.events.find((e) => e.type === 'EXIT'))

const REASON_TEXT: Record<string, string> = { TP: '止盈', SL: '止损', FORCE: '强平' }

function fmtPrice(v: number | null | undefined): string {
  return v != null ? v.toFixed(2) : '-'
}

function fmtPct(v: number | null | undefined): string {
  return v != null ? `${(v * 100).toFixed(2)}%` : '-'
}

/** 找 >= t 的最近bar时间（markLine/markArea 的 category 必须精确命中） */
function nearestTime(times: string[], t: string | undefined): string | null {
  if (!t) return null
  const hm = t.slice(0, 5)
  for (const x of times) {
    if (x >= hm) return x
  }
  return null
}

async function load() {
  loading.value = true
  try {
    data.value = await strategyApi.getStrategyIndicators(
      props.strategyId,
      store.selectedAccountId || undefined
    )
    await nextTick()
    renderChart()
  } catch (e: any) {
    ElMessage.error(`加载指标数据失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

/** 信号开/结束事件标注 */
function buildEventPoints(d: StrategyIndicators): any[] {
  return d.events.map((e) => ({
    name:
      e.type === 'ENTRY'
        ? e.side === 1
          ? '开多'
          : '开空'
        : REASON_TEXT[e.reason] || '平仓',
    coord: [e.time, e.price],
    itemStyle: {
      color:
        e.type === 'ENTRY' ? (e.side === 1 ? '#ec0000' : '#00da3c') : '#e6a23c',
    },
  }))
}

/** 开平仓参考线：开仓价/止盈/止损（高波模式无固定止盈） */
function buildPriceLines(d: StrategyIndicators): any[] {
  const lines: any[] = []
  const entry = d.events.find((e) => e.type === 'ENTRY')
  if (!entry) return lines
  const tpPct = d.params.take_profit_pct ?? 0
  const slPct = d.params.stop_loss_pct ?? 0
  lines.push({
    yAxis: entry.price,
    lineStyle: { color: '#409eff' },
    label: { formatter: '开仓 {c}', fontSize: 10 },
  })
  if (d.mode === 0 && tpPct > 0) {
    const tp = entry.side === 1 ? entry.price * (1 + tpPct) : entry.price * (1 - tpPct)
    lines.push({
      yAxis: Number(tp.toFixed(2)),
      lineStyle: { color: '#f56c6c', type: 'dashed' },
      label: { formatter: '止盈 {c}', fontSize: 10 },
    })
  }
  if (slPct > 0) {
    const sl = entry.side === 1 ? entry.price * (1 - slPct) : entry.price * (1 + slPct)
    lines.push({
      yAxis: Number(sl.toFixed(2)),
      lineStyle: { color: '#67c23a', type: 'dashed' },
      label: { formatter: d.mode === 1 ? '止损(5分收盘确认) {c}' : '止损 {c}', fontSize: 10 },
    })
  }
  return lines
}

/** 价格轴范围扩展：markLine不参与y轴自适应，超出K线范围的参考线（止盈/止损/昨收）会被裁剪 */
function expandPriceAxis(lines: any[]): {
  min: (v: { min: number }) => number
  max: (v: { max: number }) => number
} {
  const values = lines
    .map((l) => l.yAxis)
    .filter((v): v is number => typeof v === 'number')
  return {
    min: (v) => (values.length ? Math.min(v.min, ...values) : v.min),
    max: (v) => (values.length ? Math.max(v.max, ...values) : v.max),
  }
}

function renderChart() {
  if (!chartRef.value || !hasData.value || !data.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
  const option =
    data.value.mode === 1 ? buildHvOption(data.value) : buildRsiOption(data.value)
  chartInstance.setOption(option, true)
  chartInstance.resize()
}

/** 普通RSI模式：K线 + RSI副图 */
function buildRsiOption(d: StrategyIndicators): echarts.EChartsOption {
  const times = d.bars.map((b) => b.time)
  const klineData = d.bars.map((b) => [b.open, b.close, b.low, b.high])

  // K线参考线：开/止盈/止损 + 强平时间竖线
  const klineMarkLines = buildPriceLines(d)
  const forceX = nearestTime(times, d.params.force_exit_time)
  if (forceX) {
    klineMarkLines.push({
      xAxis: forceX,
      lineStyle: { color: '#909399', type: 'dashed' },
      label: { formatter: '强平', fontSize: 10 },
    })
  }

  // 交易窗口高亮
  const winStart = nearestTime(times, d.params.trade_start_time)
  const winEnd = nearestTime(times, d.params.trade_end_time)

  // RSI阈值线（多空阈值及其镜像，去重）
  const p = d.params
  const thresholds = [
    ...new Set(
      [p.short_threshold, p.long_threshold, 100 - (p.short_threshold ?? NaN), 100 - (p.long_threshold ?? NaN)].filter(
        (v): v is number => v != null && Number.isFinite(v)
      )
    ),
  ]

  return {
    animation: false,
    legend: { data: ['K线', '短RSI', '长RSI'], top: 0 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: [{ left: 60, right: 60, top: 30, bottom: 60 }],
    xAxis: [{ type: 'category', data: times, gridIndex: 0 }],
    yAxis: [
      { scale: true, gridIndex: 0, ...expandPriceAxis(klineMarkLines) },
      {
        min: 0,
        max: 100,
        gridIndex: 0,
        position: 'right',
        splitLine: { show: false },
        axisLabel: { color: '#909399' },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0] },
      { type: 'slider', xAxisIndex: [0], bottom: 4 },
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
        markPoint: {
          symbol: 'circle',
          symbolSize: 7,
          label: { show: true, position: 'top', fontSize: 10, formatter: '{b}' },
          data: buildEventPoints(d),
        },
        markLine: { silent: true, symbol: 'none', data: klineMarkLines },
        markArea:
          winStart && winEnd
            ? {
                silent: true,
                itemStyle: { color: 'rgba(64, 158, 255, 0.06)' },
                label: { show: true, position: 'insideTop', fontSize: 10, color: '#909399' },
                data: [[{ name: '交易窗口', xAxis: winStart }, { xAxis: winEnd }]],
              }
            : undefined,
      },
      {
        name: '短RSI',
        type: 'line',
        yAxisIndex: 1,
        data: d.bars.map((b) => b.rsi_short),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#409eff', opacity: 0.85 },
        markLine: {
          silent: true,
          symbol: 'none',
          data: thresholds.map((v) => ({
            yAxis: v,
            lineStyle: { color: '#c0c4cc', type: 'dashed' },
            label: { formatter: String(v), fontSize: 10, position: 'insideEndTop' },
          })),
        },
      },
      {
        name: '长RSI',
        type: 'line',
        yAxisIndex: 1,
        data: d.bars.map((b) => b.rsi_long),
        connectNulls: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#e6a23c', opacity: 0.85 },
      },
    ],
  }
}

/** 高波模式：当日K线 + 昨收/今开/09:45收参考线 + 判定标注 */
function buildHvOption(d: StrategyIndicators): echarts.EChartsOption {
  const times = d.bars.map((b) => b.time)
  const klineData = d.bars.map((b) => [b.open, b.close, b.low, b.high])

  const markLines = buildPriceLines(d)
  const refLines: Array<[number | null | undefined, string, string]> = [
    [d.hv?.prev_close, '#909399', '昨收'],
    [d.hv?.day_open, '#b88230', '今开'],
    [d.hv?.close_0945, '#626aef', '09:45收'],
  ]
  for (const [value, color, name] of refLines) {
    if (value != null) {
      markLines.push({
        yAxis: value,
        lineStyle: { color, type: 'dashed' },
        label: { formatter: `${name} {c}`, fontSize: 10 },
      })
    }
  }

  const markPoints = buildEventPoints(d)
  if (d.hv?.decided && d.hv.close_0945 != null && times.includes('09:45')) {
    markPoints.push({
      name: '判定',
      coord: ['09:45', d.hv.close_0945],
      itemStyle: { color: '#626aef' },
    })
  }

  return {
    animation: false,
    legend: { data: ['K线'], top: 0 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    grid: [{ left: 60, right: 30, top: 30, bottom: 60 }],
    xAxis: [{ type: 'category', data: times, gridIndex: 0 }],
    yAxis: [{ scale: true, gridIndex: 0, ...expandPriceAxis(markLines) }],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0] },
      { type: 'slider', xAxisIndex: [0], bottom: 4 },
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
        markPoint: {
          symbol: 'circle',
          symbolSize: 7,
          label: { show: true, position: 'top', fontSize: 10, formatter: '{b}' },
          data: markPoints,
        },
        markLine: { silent: true, symbol: 'none', data: markLines },
      },
    ],
  }
}

function handleResize() {
  isMobile.value = window.innerWidth <= 768
  chartInstance?.resize()
}

watch(
  () => store.selectedAccountId,
  () => load()
)

onMounted(() => {
  load()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.hv-desc {
  margin-bottom: 12px;
}

.chart-container {
  width: 100%;
  height: 480px;
}
</style>
