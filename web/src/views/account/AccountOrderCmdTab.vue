<template>
  <div class="account-order-cmd-tab">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>报单指令</span>
          <el-space>
            <el-radio-group v-model="localStatus" @change="emit('refresh')">
              <el-radio-button label="active">未完成</el-radio-button>
              <el-radio-button label="finished">已完成</el-radio-button>
            </el-radio-group>
            <el-button type="primary" data-testid="create-order-cmd-btn" @click="showCreateDialog = true">
              <el-icon><Plus /></el-icon>
              新增
            </el-button>
            <el-button type="primary" @click="emit('refresh')" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </el-space>
        </div>
      </template>

      <div class="table-wrapper">
        <el-table :data="sortedOrderCmds" stripe v-loading="loading" :size="isMobile ? 'small' : 'default'">
          <template #empty>
            <el-empty description="暂无报单指令" />
          </template>
          <el-table-column v-if="!isMobile" prop="cmd_id" label="指令ID" width="180" show-overflow-tooltip />
          <el-table-column v-if="!isMobile" prop="source" label="来源" width="150" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.source || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="symbol" label="合约" width="80" />
          <el-table-column v-if="!isMobile && localStatus === 'active'" prop="status" label="状态" :width="isMobile ? 70 : 100">
            <template #default="{ row }">
              <el-tag :type="getOrderCmdStatusType(row.status)" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="volume" label="总手" :width="isMobile ? 60 : 100" />
          <el-table-column prop="filled_volume" label="成交" :width="isMobile ? 60 : 120" />
          <el-table-column prop="limit_price" label="限价" :width="isMobile ? 60 : 100">
            <template #default="{ row }">
              {{ row.limit_price ? formatNumber(row.limit_price) : '市价' }}
            </template>
          </el-table-column>
          <el-table-column prop="direction" label="方向" :width="isMobile ? 50 : 80">
            <template #default="{ row }">
              <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small" v-if="row.direction">
                {{ row.direction === 'BUY' ? '买' : '卖' }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="offset" label="开平" :width="isMobile ? 60 : 80">
            <template #default="{ row }">
              {{ row.offset || '-' }}
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" prop="started_at" label="开始时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.started_at) }}
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" prop="finished_at" label="结束时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.finished_at) }}
            </template>
          </el-table-column>
          <el-table-column v-if="!isMobile" prop="total_orders" label="总报单" width="100" />
          <el-table-column v-if="!isMobile" prop="finish_reason" label="结束原因" width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span :class="getFinishReasonClass(row.finish_reason)">{{ row.finish_reason || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="localStatus === 'active'"
            label="操作"
            :width="isMobile ? 60 : 100"
            fixed="right"
          >
            <template #default="{ row }">
              <el-button
                type="danger"
                :size="isMobile ? 'small' : 'default'"
                @click="emit('cancelOrderCmd', row.cmd_id)"
                :loading="cancellingCmdId === row.cmd_id"
              >
                取消
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 新增报单指令对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      title="新增报单指令"
      width="90%"
      style="max-width: 500px"
      @open="resetCreateForm"
    >
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="合约代码" required>
          <el-input
            v-model="createForm.symbol"
            data-testid="create-order-cmd-symbol"
            :placeholder="symbolPlaceholder"
          />
        </el-form-item>
        <el-form-item label="买卖方向" required>
          <el-select v-model="createForm.direction" data-testid="create-order-cmd-direction">
            <el-option label="买入" value="BUY" />
            <el-option label="卖出" value="SELL" />
          </el-select>
        </el-form-item>
        <el-form-item label="开平标志" required>
          <el-select v-model="createForm.offset" data-testid="create-order-cmd-offset">
            <el-option label="开仓" value="OPEN" />
            <el-option label="平仓" value="CLOSE" />
            <el-option label="平今" value="CLOSETODAY" />
          </el-select>
        </el-form-item>
        <el-form-item label="手数" required>
          <el-input-number
            v-model="createForm.volume"
            :min="1"
            :max="1000"
            data-testid="create-order-cmd-volume"
          />
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number
            v-model="createForm.price"
            :min="0"
            :step="0.01"
            :precision="2"
            data-testid="create-order-cmd-price"
            placeholder="0表示市价"
          />
          <span class="price-hint">0 表示市价（对手价追价报单）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button data-testid="create-order-cmd-cancel" @click="showCreateDialog = false">取消</el-button>
        <el-button
          type="primary"
          data-testid="create-order-cmd-submit"
          :loading="creating"
          @click="handleCreate"
        >
          发送指令
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import type { OrderCmd } from '@/types'
import { useStore } from '@/stores'

const props = defineProps<{
  loading: boolean
  orderCmds: OrderCmd[]
  status: 'active' | 'finished'
  cancellingCmdId: string | null
}>()

const emit = defineEmits<{
  refresh: []
  cancelOrderCmd: [cmdId: string]
  createOrderCmd: [form: { symbol: string; direction: 'BUY' | 'SELL'; offset: string; volume: number; price: number }]
  'update:status': [status: 'active' | 'finished']
}>()

const localStatus = computed({
  get: () => props.status,
  set: (val) => emit('update:status', val)
})

const isMobile = ref(false)

// ==================== 新增报单指令 ====================
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = reactive({
  symbol: '',
  direction: 'BUY' as 'BUY' | 'SELL',
  offset: 'OPEN',
  volume: 1,
  price: 0
})

function resetCreateForm() {
  createForm.symbol = ''
  createForm.direction = 'BUY'
  createForm.offset = 'OPEN'
  createForm.volume = 1
  createForm.price = 0
}

async function handleCreate() {
  if (!createForm.symbol.trim()) {
    ElMessage.warning('请填写合约代码')
    return
  }
  if (!createForm.volume || createForm.volume <= 0) {
    ElMessage.warning('手数必须大于0')
    return
  }
  creating.value = true
  try {
    emit('createOrderCmd', {
      symbol: createForm.symbol.trim(),
      direction: createForm.direction,
      offset: createForm.offset,
      volume: createForm.volume,
      price: createForm.price || 0
    })
    showCreateDialog.value = false
  } finally {
    creating.value = false
  }
}

const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 768
}

// 合约输入框占位提示：后端最新螺纹钢主力（如 SHFE.rb2701）
const store = useStore()
const symbolPlaceholder = ref('如: SHFE.rb2505')

onMounted(() => {
  updateIsMobile()
  window.addEventListener('resize', updateIsMobile)
  store.loadMainSymbol().then((s) => {
    if (s) symbolPlaceholder.value = `如: SHFE.${s}`
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', updateIsMobile)
})

// 按开始时间倒序排序的报单指令
const sortedOrderCmds = computed(() => {
  if (!props.orderCmds || props.orderCmds.length === 0) return []
  return [...props.orderCmds].sort((a, b) => {
    const timeA = a.started_at ? new Date(a.started_at).getTime() : 0
    const timeB = b.started_at ? new Date(b.started_at).getTime() : 0
    return timeB - timeA
  })
})

function formatNumber(num: number | null | undefined): string {
  if (num === null || num === undefined) return '0.00'
  return num.toFixed(2)
}

function formatDateTime(datetime: string | number | null | undefined): string {
  if (!datetime) return '-'
  const date = typeof datetime === 'number'
    ? new Date(datetime * 1000)
    : new Date(datetime)
  return date.toLocaleString('zh-CN')
}

function getOrderCmdStatusType(status: string): string {
  switch (status) {
    case 'RUNNING':
      return 'success'
    case 'FINISHED':
      return 'info'
    case 'CANCELING':
      return 'warning'
    default:
      return 'info'
  }
}

// 结束原因着色：全部完成绿色，取消/超时黄色，其他（报单被拒/拆单失败等异常）红色
function getFinishReasonClass(reason: string | null | undefined): string {
  if (!reason) return ''
  if (reason === 'ALL_COMPLETED') return 'reason-success'
  if (reason === 'CANCELLED' || reason === 'TIMEOUT' || reason.includes('取消')) return 'reason-warning'
  return 'reason-danger'
}
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

.price-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}

.reason-success {
  color: #67c23a;
  font-weight: 600;
}

.reason-warning {
  color: #e6a23c;
  font-weight: 600;
}

.reason-danger {
  color: #f56c6c;
  font-weight: 600;
}
</style>
