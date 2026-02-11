<template>
  <div class="strategy-details">
    <el-page-header @back="goBack" :title="`策略详情 - ${strategyId}`" class="header" />

    <el-skeleton v-if="loading" :rows="6" animated />

    <template v-else>
      <!-- 策略基本信息及操作 -->
      <el-card shadow="hover" class="section">
        <template #header>
          <span>基本信息</span>
        </template>
        <el-descriptions :column="3" border v-if="strategy">
          <el-descriptions-item label="策略ID">{{ strategy.strategy_id }}</el-descriptions-item>
          <el-descriptions-item label="合约">{{ strategy.params?.symbol || strategy.config?.symbol || '-' }}</el-descriptions-item>
          <el-descriptions-item label="启用开关">
            <el-switch
              v-model="strategy.enabled"
              @change="handleToggleEnabled"
              :loading="actionLoading"
            />
          </el-descriptions-item>
          <el-descriptions-item label="交易控制">
            <el-space :size="20">
              <el-checkbox
                v-model="strategy.opening_paused"
                @change="handleTradingStatusChange"
              >
                暂停开仓
              </el-checkbox>
              <el-checkbox
                v-model="strategy.closing_paused"
                @change="handleTradingStatusChange"
              >
                暂停平仓
              </el-checkbox>
            </el-space>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

    <!-- 策略参数设置 -->
    <el-card shadow="hover" class="section">
      <template #header>
        <span>参数设置</span>
      </template>
      <el-form :model="paramsForm" label-width="140px" v-if="strategy">
        <!-- 基础参数 -->
        <el-divider content-position="left">基础参数</el-divider>
        <el-row :gutter="20">
          <el-col v-for="param in strategy.base_params" :key="param.key" :span="8">
            <el-form-item :label="param.label">
              <el-input v-if="param.type === 'string'" v-model="paramsForm[param.key]" style="width: 60%"/>
              <el-input-number
                v-else-if="param.type === 'int' || param.type === 'float'"
                v-model="paramsForm[param.key]"
                :step="param.type === 'float' ? 0.001 : 1"
                :precision="param.type === 'float' ? 4 : 0"
                style="width: 60%"
              />
              <el-switch v-else-if="param.type === 'bool'" v-model="paramsForm[param.key]" />
              <el-time-picker
                v-else-if="param.type === 'time'"
                v-model="paramsForm[param.key]"
                format="HH:mm:ss"
                value-format="HH:mm:ss"
                style="width: 60%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 扩展参数 -->
        <el-divider content-position="left">扩展参数</el-divider>
        <el-row :gutter="20" v-if="strategy.ext_params && strategy.ext_params.length > 0">
          <el-col v-for="param in strategy.ext_params" :key="param.key" :span="8">
            <el-form-item :label="param.label">
              <el-input v-if="param.type === 'string'" v-model="paramsForm[param.key]" style="width: 60%" />
              <el-input-number
                v-else-if="param.type === 'int' || param.type === 'float'"
                v-model="paramsForm[param.key]"
                :step="param.type === 'float' ? 0.001 : 1"
                :precision="param.type === 'float' ? 4 : 0"
                style="width: 60%"
              />
              <el-switch v-else-if="param.type === 'bool'" v-model="paramsForm[param.key]" />
              <el-time-picker
                v-else-if="param.type === 'time'"
                v-model="paramsForm[param.key]"
                format="HH:mm:ss"
                value-format="HH:mm:ss"
                style="width: 60%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item>
          <el-space>
            <el-button type="primary" @click="handleSaveParams" :loading="saveLoading">保存参数</el-button>
            <el-button @click="handleReloadParams" :loading="actionLoading">重载参数</el-button>
            <el-button @click="handleInitStrategy" :loading="actionLoading">初始化策略</el-button>
          </el-space>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 策略信号设置 -->
    <el-card shadow="hover" class="section">
      <template #header>
        <span>信号与持仓</span>
      </template>
      <el-form :model="signalForm" label-width="140px" v-if="strategy">
        <el-row :gutter="20">
          <el-col :span="24">
            <el-form-item label="信号方向">
              <el-radio-group v-model="signalForm.side">
                <el-radio :label="0">无信号</el-radio>
                <el-radio :label="1">多头</el-radio>
                <el-radio :label="-1">空头</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 入场信息 -->
        <template v-if="signalForm.side !== 0">
          <el-divider content-position="left">入场信息</el-divider>
          <el-row :gutter="20">
            <el-col :span="8">
              <el-form-item label="入场时间">
                <el-time-picker
                  v-model="signalForm.entry_time"
                  format="HH:mm:ss"
                  value-format="HH:mm:ss"
                  placeholder="选择时间"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="入场价格">
                <el-input-number v-model="signalForm.entry_price" :min="0" :step="0.1" :precision="2" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="入场手数">
                <el-input-number v-model="signalForm.entry_volume" :min="1" :max="100" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 退场信息 -->
          <el-divider content-position="left">退场信息</el-divider>
          <el-row :gutter="20">
            <el-col :span="8">
              <el-form-item label="退场时间">
                <el-time-picker
                  v-model="signalForm.exit_time"
                  format="HH:mm:ss"
                  value-format="HH:mm:ss"
                  placeholder="选择时间"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="退场价格">
                <el-input-number v-model="signalForm.exit_price" :min="0" :step="0.1" :precision="2" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="退场原因">
                <el-input v-model="signalForm.exit_reason" placeholder="退场原因" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <el-divider content-position="left">当前持仓状态</el-divider>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="多头持仓">
              <el-input-number v-model="signalForm.pos_long" :min="0" :max="100" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="空头持仓">
              <el-input-number v-model="signalForm.pos_short" :min="0" :max="100" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="持仓均价">
              <el-input-number v-model="signalForm.pos_price" :min="0" :step="0.1" :precision="2" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item>
          <el-button type="primary" @click="handleSaveSignal" :loading="saveLoading">保存信号</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 报单指令历史 -->
    <el-card shadow="hover" class="section">
      <template #header>
        <div class="card-header">
          <span>报单指令历史</span>
          <div class="header-actions">
            <el-button type="primary" size="small" @click="showAddOrderCmdDialog">新增指令</el-button>
            <el-radio-group v-model="orderCmdFilter" @change="loadOrderCmds" size="small">
              <el-radio-button label="active">进行中</el-radio-button>
              <el-radio-button label="finished">已完成</el-radio-button>
              <el-radio-button label="all">全部</el-radio-button>
            </el-radio-group>
          </div>
        </div>
      </template>
      <el-table :data="orderCmds" stripe v-loading="orderCmdsLoading" table-layout="auto">
        <el-table-column prop="cmd_id" label="指令ID" width="120" show-overflow-tooltip/>
        <el-table-column prop="symbol" label="合约" width="120" />
        <el-table-column label="方向" width="80">
          <template #default="{ row }">
            <el-tag :type="row.direction === 'BUY' ? 'danger' : 'primary'" size="small">
              {{ row.direction === 'BUY' ? '买' : '卖' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开平" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ getOffsetText(row.offset) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="目标手数" width="100" />
        <el-table-column prop="filled_volume" label="已成交" width="100" />
        <el-table-column prop="filled_price" label="成交均价" width="100">
          <template #default="{ row }">{{ row.filled_price?.toFixed(2) || '-' }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="finish_reason" label="完成原因" width="180"  show-overflow-tooltip/>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
    </template>

    <!-- 新增指令对话框 -->
    <el-dialog v-model="addOrderCmdDialogVisible" title="新增报单指令" width="500px">
      <el-form :model="orderCmdForm" label-width="100px" :rules="orderCmdFormRules" ref="orderCmdFormRef">
        <el-form-item label="合约代码" prop="symbol">
          <el-input v-model="orderCmdForm.symbol" placeholder="如: CFFEX.IM2603" />
        </el-form-item>
        <el-form-item label="操作类型" prop="offset">
          <el-select v-model="orderCmdForm.offset" placeholder="请选择">
            <el-option label="开仓" value="OPEN" />
            <el-option label="平仓" value="CLOSE" />
            <el-option label="平今" value="CLOSETODAY" />
          </el-select>
        </el-form-item>
        <el-form-item label="方向" prop="direction">
          <el-radio-group v-model="orderCmdForm.direction">
            <el-radio label="BUY">买入</el-radio>
            <el-radio label="SELL">卖出</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="手数" prop="volume">
          <el-input-number v-model="orderCmdForm.volume" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="目标价格" prop="price">
          <el-input-number v-model="orderCmdForm.price" :min="0" :step="0.1" :precision="2" placeholder="0表示市价" />
          <div class="form-tip">设置为0表示市价单</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addOrderCmdDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAddOrderCmd" :loading="addOrderCmdLoading">发送</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useStore } from '@/stores'
import { strategyApi } from '@/api'

const router = useRouter()
const route = useRoute()
const store = useStore()

const strategyId = route.params.strategyId as string
const strategy = ref<any>(null)
const loading = ref(false)
const actionLoading = ref(false)
const saveLoading = ref(false)

const paramsForm = ref<Record<string, any>>({
  symbol: '',
  bar: 'M1',
  volume_per_trade: 1,
  max_position: 5,
  take_profit_pct: 0.015,
  stop_loss_pct: 0.015,
  slippage: 0,
  force_exit_time: '14:55:00'
})

const signalForm = ref<any>({
  side: 0,
  entry_time: '',
  entry_price: 0,
  entry_volume: 1,
  exit_time: '',
  exit_price: 0,
  exit_reason: '',
  pos_long: 0,
  pos_short: 0,
  pos_price: null
})

const orderCmds = ref<any[]>([])
const orderCmdsLoading = ref(false)
const orderCmdFilter = ref<'all' | 'active' | 'finished'>('active')

// 新增指令对话框
const addOrderCmdDialogVisible = ref(false)
const addOrderCmdLoading = ref(false)
const orderCmdFormRef = ref()
const orderCmdForm = ref({
  symbol: '',
  direction: 'BUY' as 'BUY' | 'SELL',
  offset: 'OPEN' as 'OPEN' | 'CLOSE' | 'CLOSETODAY',
  volume: 1,
  price: 0
})
const orderCmdFormRules = {
  symbol: [{ required: true, message: '请输入合约代码', trigger: 'blur' }],
  offset: [{ required: true, message: '请选择操作类型', trigger: 'change' }],
  direction: [{ required: true, message: '请选择方向', trigger: 'change' }],
  volume: [{ required: true, message: '请输入手数', trigger: 'blur' }]
}

function goBack() {
  router.push('/strategy')
}

function formatDateTime(dateStr: string | undefined): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function getOffsetText(offset: string | undefined): string {
  const map: Record<string, string> = {
    'OPEN': '开',
    'CLOSE': '平',
    'CLOSETODAY': '平今'
  }
  return map[offset || ''] || offset || '-'
}

function getStatusType(status: string | undefined): string {
  const map: Record<string, string> = {
    'PENDING': 'info',
    'RUNNING': 'primary',
    'FINISHED': 'success'
  }
  return map[status || ''] || 'info'
}

function getStatusText(status: string | undefined): string {
  const map: Record<string, string> = {
    'PENDING': '待执行',
    'RUNNING': '执行中',
    'FINISHED': '已完成'
  }
  return map[status || ''] || status || '-'
}

async function loadStrategy() {
  loading.value = true
  try {
    strategy.value = await strategyApi.getStrategy(strategyId, store.selectedAccountId || undefined)

    // 从base_params和ext_params构建paramsForm
    if (strategy.value.base_params) {
      paramsForm.value = {}
      for (const param of [...strategy.value.base_params, ...(strategy.value.ext_params || [])]) {
        paramsForm.value[param.key] = param.value
      }
    } else {
      // 向后兼容：使用旧的params字段
      const params = strategy.value.params || {}
      const extParams = strategy.value.ext_params || {}
      paramsForm.value = {
        ...params,
        ...extParams
      }
    }

    // 初始化信号表单
    const signal = strategy.value.signal || {}
    signalForm.value = {
      side: signal.side || 0,
      entry_time: signal.entry_time || '',
      entry_price: signal.entry_price || 0,
      entry_volume: signal.entry_volume || paramsForm.value.volume_per_trade || 1,
      exit_time: signal.exit_time || '',
      exit_price: signal.exit_price || 0,
      exit_reason: signal.exit_reason || '',
      // 使用API返回的持仓数据（区分多头和空头）
      pos_long: strategy.value.pos_long || 0,
      pos_short: strategy.value.pos_short || 0,
      pos_price: strategy.value.pos_price || null
    }
  } catch (error: any) {
    ElMessage.error(`加载策略失败: ${error.message}`)
    strategy.value = null
  } finally {
    loading.value = false
  }
}

async function loadOrderCmds() {
  orderCmdsLoading.value = true
  try {
    const status = orderCmdFilter.value === 'all' ? undefined : orderCmdFilter.value
    orderCmds.value = await strategyApi.getStrategyOrderCmds(strategyId, { status }, store.selectedAccountId || undefined)
  } catch (error: any) {
    ElMessage.error(`加载报单指令失败: ${error.message}`)
  } finally {
    orderCmdsLoading.value = false
  }
}

async function handleToggleEnabled(enabled: boolean) {
  actionLoading.value = true
  try {
    if (enabled) {
      await strategyApi.enableStrategy(strategyId, store.selectedAccountId || undefined)
      ElMessage.success('策略已启用')
    } else {
      await strategyApi.disableStrategy(strategyId, store.selectedAccountId || undefined)
      ElMessage.success('策略已禁用')
    }
    await loadStrategy()
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
  } finally {
    actionLoading.value = false
  }
}

async function handleTradingStatusChange() {
  actionLoading.value = true
  try {
    await strategyApi.setTradingStatus(
      strategyId,
      {
        opening_paused: strategy.value.opening_paused,
        closing_paused: strategy.value.closing_paused
      },
      store.selectedAccountId || undefined
    )
    ElMessage.success('交易状态已更新')
  } catch (error: any) {
    ElMessage.error(`更新交易状态失败: ${error.message}`)
    await loadStrategy()
  } finally {
    actionLoading.value = false
  }
}

async function handleReloadParams() {
  actionLoading.value = true
  try {
    await strategyApi.reloadStrategyParams(strategyId, store.selectedAccountId || undefined)
    ElMessage.success('参数重载成功')
    await loadStrategy()
  } catch (error: any) {
    ElMessage.error(`重载参数失败: ${error.message}`)
  } finally {
    actionLoading.value = false
  }
}

async function handleInitStrategy() {
  actionLoading.value = true
  try {
    await strategyApi.initStrategy(strategyId, store.selectedAccountId || undefined)
    ElMessage.success('策略初始化成功')
    await loadStrategy()
  } catch (error: any) {
    ElMessage.error(`初始化策略失败: ${error.message}`)
  } finally {
    actionLoading.value = false
  }
}

async function handleSaveParams() {
  saveLoading.value = true
  try {
    await strategyApi.updateStrategy(strategyId, paramsForm.value, store.selectedAccountId || undefined)
    ElMessage.success('参数保存成功')
    await loadStrategy()
  } catch (error: any) {
    ElMessage.error(`保存参数失败: ${error.message}`)
  } finally {
    saveLoading.value = false
  }
}

async function handleSaveSignal() {
  saveLoading.value = true
  try {
    await strategyApi.updateStrategySignal(strategyId, signalForm.value, store.selectedAccountId || undefined)
    ElMessage.success('信号保存成功')
    await loadStrategy()
  } catch (error: any) {
    ElMessage.error(`保存信号失败: ${error.message}`)
  } finally {
    saveLoading.value = false
  }
}

function showAddOrderCmdDialog() {
  // 预填充合约代码
  if (strategy.value?.params?.symbol) {
    orderCmdForm.value.symbol = `${strategy.value.params.exchange || 'CFFEX'}.${strategy.value.params.symbol}`
  } else if (strategy.value?.config?.symbol) {
    orderCmdForm.value.symbol = `${strategy.value.config.exchange || 'CFFEX'}.${strategy.value.config.symbol}`
  }
  // 重置表单
  orderCmdForm.value.direction = 'BUY'
  orderCmdForm.value.offset = 'OPEN'
  orderCmdForm.value.volume = 1
  orderCmdForm.value.price = 0
  addOrderCmdDialogVisible.value = true
}

async function handleAddOrderCmd() {
  await orderCmdFormRef.value?.validate()
  addOrderCmdLoading.value = true
  try {
    const result = await strategyApi.sendStrategyOrderCmd(
      strategyId,
      {
        symbol: orderCmdForm.value.symbol,
        direction: orderCmdForm.value.direction,
        offset: orderCmdForm.value.offset,
        volume: orderCmdForm.value.volume,
        price: orderCmdForm.value.price
      },
      store.selectedAccountId || undefined
    )
    ElMessage.success(`报单指令已发送: ${result.cmd_id}`)
    addOrderCmdDialogVisible.value = false
    // 刷新报单指令列表
    await loadOrderCmds()
  } catch (error: any) {
    ElMessage.error(`发送报单指令失败: ${error.message}`)
  } finally {
    addOrderCmdLoading.value = false
  }
}

onMounted(async () => {
  await loadStrategy()
  await loadOrderCmds()
})
</script>

<style scoped>
.strategy-details {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.header {
  margin-bottom: 20px;
}

.header :deep(.el-page-header__title) {
  color: #409eff;
}

.header :deep(.el-page-header__content) {
  color: #409eff;
}

.header :deep(.el-icon) {
  color: #409eff;
}

.section {
  margin-bottom: 20px;
}

.action-buttons {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--el-border-color);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
</style>
