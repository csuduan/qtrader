<template>
  <div class="rotation">
    <el-card shadow="hover">
        <template #header>
          <div class="card-header">
            <div>
              <span>换仓指令管理</span>
            </div>
            <div class="header-actions">
              <el-tag v-if="rotationStatus.working" :type="rotationStatus.is_manual ? 'success' : 'warning'" size="large" style="margin-right: 10px">
                {{ rotationStatus.is_manual ? '手动换仓中' : '自动换仓中' }}
              </el-tag>
              <el-button @click="handleStartRotation" :loading="rotating" :disabled="rotationStatus.working" type="success">
                <el-icon><VideoPlay /></el-icon>
                开始换仓
              </el-button>
              <el-button @click="handleBatchDelete" :loading="batchDeleting" :disabled="selectedInstructions.length === 0 || rotationStatus.working" type="danger">
                <el-icon><Delete /></el-icon>
                删除选中
              </el-button>
              <el-button @click="handleClear" :disabled="rotationStatus.working">
                <el-icon><Delete /></el-icon>
                清除已完成
              </el-button>
              <el-button @click="showImportDialog = true" :disabled="rotationStatus.working">
                <el-icon><Upload /></el-icon>
                导入CSV
              </el-button>
              <el-button @click="loadData" :loading="loading">
                <el-icon><Refresh /></el-icon>
                刷新
              </el-button>
            </div>
          </div>
        </template>

          <el-table
            :data="instructions"
            :row-class-name="tableRowClassName"
            table-layout="fixed"
            @selection-change="handleSelectionChange"
          >
          <el-table-column type="selection" width="55" />
          <el-table-column prop="strategy_id" label="策略编号" width="150" />
          <el-table-column label="合约" width="150" fixed>
            <template #default="{ row }">
              {{ row.symbol }}
            </template>
          </el-table-column>
          <el-table-column prop="direction" label="方向" width="70">
            <template #default="{ row }">
              <el-tag :type="row.direction === 'BUY' ? 'success' : 'danger'" size="small">
                {{ row.direction === 'BUY' ? '买' : '卖' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="offset" label="开平" width="70" />
          <el-table-column prop="volume" label="手数" width="70" />
          <el-table-column label="进度" width="120">
            <template #default="{ row }">
              <el-progress
                :percentage="getProgress(row.volume, row.remaining_volume)"
                :format="() => `${row.volume - row.remaining_volume}/${row.volume}`"
              />
            </template>
          </el-table-column>
          <el-table-column label="信息"  show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.status === 'COMPLETED'" style="color: #67c23a">已完成</span>
              <span v-else style="color: #f56c6c">{{ row.error_message || '待执行' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="order_time" label="报单时间" width="100">
            <template #default="{ row }">
              {{ row.order_time || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="enabled" label="启用" width="70">
            <template #default="{ row }">
              <el-switch
                v-model="row.enabled"
                @change="handleToggleEnable(row)"
              />
            </template>
          </el-table-column>
          <el-table-column prop="updated_at" label="更新时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.updated_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="150" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.source || '-' }}
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="instructions.length === 0" description="暂无换仓指令" />
      </el-card>

    <!-- 导入CSV对话框 -->
    <el-dialog
      v-model="showImportDialog"
      title="导入换仓CSV"
      width="700px"
      @open="handleDialogOpen"
    >
      <el-alert
        title="CSV格式参考实例"
        type="info"
        :closable="false"
        style="margin-bottom: 15px"
      >
        <div style="font-size: 12px; line-height: 1.8; font-family: monospace; background: #f5f7fa; padding: 10px; border-radius: 4px;">
          账户编号,策略编号,合约,开平,方向,手数,报单时间<br>
          DQ,StrategyFix_PK,PK603.CZC,Close,Sell,2,09:05:00<br>
          DQ,StrategyFix_RM,RM605.CZC,Close,Sell,4,<br>
          DQ,StrategyFix_JD,JD2603.DCE,Open,Sell,1,09:05:00
        </div>
      </el-alert>

      <el-form :model="importForm" label-width="100px">
        <el-form-item label="CSV文件">
          <el-upload
            ref="uploadRef"
            accept=".csv"
            :auto-upload="false"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :limit="1"
          >
            <el-button type="primary">选择文件</el-button>
          </el-upload>
        </el-form-item>

        <el-form-item v-if="csvPreview.length > 0" label="预览前5行">
          <el-table :data="csvPreview" size="small" border max-height="200">
            <el-table-column
              v-for="(header, index) in csvHeaders"
              :key="index"
              :prop="`col${index}`"
              :label="header"
              :width="120"
              show-overflow-tooltip
            >
            </el-table-column>
          </el-table>
        </el-form-item>

        <el-form-item label="导入方式">
          <el-radio-group v-model="importMode">
            <el-radio label="replace">替换现有数据</el-radio>
            <el-radio label="append">追加到现有数据</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-progress v-if="importing" :percentage="uploadPercentage" :status="uploadStatus">
          正在导入 {{ uploadPercentage }}%
        </el-progress>
      </el-form>
      <template #footer>
        <el-button @click="showImportDialog = false" :disabled="importing">取消</el-button>
        <el-button type="primary" @click="handleImport" :loading="importing" :disabled="csvPreview.length === 0">
          确认导入
        </el-button>
      </template>
    </el-dialog>

    <!-- 新增指令对话框 -->
    <el-dialog v-model="showCreateDialog" title="新增换仓指令" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="账户编号">
          <el-input v-model="form.account_id" placeholder="如: DQ" />
        </el-form-item>
        <el-form-item label="策略编号">
          <el-input v-model="form.strategy_id" placeholder="如: StrategyFix_PK" />
        </el-form-item>
        <el-form-item label="合约代码">
          <el-input v-model="form.symbol" placeholder="如: rb2505" />
        </el-form-item>
        <el-form-item label="交易所代码">
          <el-input v-model="form.exchange_id" placeholder="如: SHFE" />
        </el-form-item>
        <el-form-item label="买卖方向">
          <el-select v-model="form.direction" placeholder="请选择">
            <el-option label="买入" value="BUY" />
            <el-option label="卖出" value="SELL" />
          </el-select>
        </el-form-item>
        <el-form-item label="开平标志">
          <el-select v-model="form.offset" placeholder="请选择">
            <el-option label="开仓" value="OPEN" />
            <el-option label="平仓" value="CLOSE" />
            <el-option label="平今" value="CLOSETODAY" />
          </el-select>
        </el-form-item>
        <el-form-item label="手数">
          <el-input-number v-model="form.volume" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number
            v-model="form.price"
            :min="0"
            :step="0.01"
            :precision="2"
            placeholder="0表示市价"
          />
        </el-form-item>
        <el-form-item label="报单时间">
          <el-input
            v-model="form.order_time"
            placeholder="格式: HH:MM:SS，不填则无限制"
          />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type UploadInstance, type UploadUserFile } from 'element-plus'
import { VideoPlay, Refresh, Delete, Upload } from '@element-plus/icons-vue'
import { rotationApi } from '@/api'
import { useStore } from '@/stores'
import type { RotationInstruction } from '@/types'

const store = useStore()

 const loading = ref(false)
 const creating = ref(false)
 const rotating = ref(false)
 const batchDeleting = ref(false)
 const showCreateDialog = ref(false)
 const showImportDialog = ref(false)
 const importMode = ref('append')
 const uploading = ref(false)
 const importing = ref(false)
 const uploadPercentage = ref(0)
 const uploadStatus = ref('')
 const uploadRef = ref<UploadInstance>()
 const instructions = ref<RotationInstruction[]>([])
 const rotationStatus = reactive({ working: false, is_manual: false })
 const selectedInstructions = ref<RotationInstruction[]>([])
 const csvPreview = ref<Record<string, string>[]>([])
 const csvHeaders = ref<string[]>([])
 const importForm = reactive({ file: null as UploadUserFile | null })

// uploadRef is used in template via ref="uploadRef"
void uploadRef

const form = reactive({
  account_id: '',
  strategy_id: '',
  symbol: '',
  exchange_id: '',
  direction: 'BUY',
  offset: 'OPEN',
  volume: 1,
  price: 0,
  order_time: '',
  enabled: true
})

const tableRowClassName = ({ row }: { row: RotationInstruction }) => {
  return row.enabled ? '' : 'disabled-row'
}

function handleSelectionChange(selection: RotationInstruction[]) {
  selectedInstructions.value = selection
}

async function handleStartRotation() {
  try {
    await ElMessageBox.confirm('确定要开始换仓流程吗？将自动执行所有符合条件的指令。', '确认换仓', {
      type: 'warning'
    })

    rotating.value = true
    await rotationApi.startRotation(store.selectedAccountId || undefined)
    ElMessage.success('换仓流程已启动，正在执行...')
    await loadData()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`启动换仓失败: ${error.message}`)
    }
  } finally {
    rotating.value = false
  }
}

async function handleBatchDelete() {
  if (selectedInstructions.value.length === 0) {
    ElMessage.warning('请先选择要删除的指令')
    return
  }

  try {
    await ElMessageBox.confirm(`确定要删除 ${selectedInstructions.value.length} 条指令吗？`, '确认删除', {
      type: 'warning'
    })

    batchDeleting.value = true
    const ids = selectedInstructions.value.map(item => item.id)
    const result = await rotationApi.batchDeleteInstructions(ids, store.selectedAccountId || undefined)
    ElMessage.success(`删除成功，共 ${result.deleted} 条`)
    selectedInstructions.value = []
    await loadData()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`删除失败: ${error.message}`)
    }
  } finally {
    batchDeleting.value = false
  }
}

function getProgress(total: number, remaining: number): number {
  if (total === 0) return 0
  return Math.round(((total - remaining) / total) * 100)
}


function handleDialogOpen() {
  importForm.file = null
  csvPreview.value = []
  csvHeaders.value = []
  uploadPercentage.value = 0
  uploadStatus.value = ''
}

function handleFileRemove() {
  importForm.file = null
  csvPreview.value = []
  csvHeaders.value = []
}

const handleFileChange = (file: UploadUserFile) => {
  uploadPercentage.value = 0
  uploading.value = true
  uploadStatus.value = 'uploading'
  importForm.file = file

  const reader = new FileReader()
  reader.onload = (e: ProgressEvent<FileReader>) => {
    try {
      const text = e.target?.result as string
      const lines = text.split('\n')

      if (lines.length > 0 && lines[0]) {
        const header = lines[0].trim().split(',')
        csvHeaders.value = header

        const previewData: Record<string, string>[] = []
        const previewLines = lines.slice(1, 6)

        for (let i = 0; i < previewLines.length; i++) {
          const line = previewLines[i]
          if (!line) continue

          const values = line.trim().split(',')
          const row: Record<string, string> = {}

          header.forEach((_, index) => {
            row[`col${index}`] = values[index] || ''
          })

          if (values.length > 0 && values[0]) {
            previewData.push(row)
          }
        }

        csvPreview.value = previewData
      }

      ElMessage.success(`文件已解析，共 ${lines.length - 1} 行数据`)
      uploading.value = false
    } catch (error: any) {
      ElMessage.error(`解析CSV失败: ${error.message}`)
      uploading.value = false
    }
  }

  reader.readAsText(file.raw as File, 'GBK')
}

async function loadData() {
  loading.value = true
  try {
    const result = await rotationApi.getRotationInstructions({
      account_id: store.selectedAccountId || undefined
    })
    instructions.value = result.instructions
    Object.assign(rotationStatus, result.rotation_status)
  } catch (error: any) {
    ElMessage.error(`加载换仓指令失败: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!form.account_id || !form.strategy_id || !form.symbol || !form.exchange_id ||
      !form.direction || !form.offset || form.volume <= 0) {
    ElMessage.warning('请填写完整的指令信息')
    return
  }

  creating.value = true
  try {
    await rotationApi.createRotationInstruction({
      ...form,
      account_id: store.selectedAccountId || form.account_id
    })
    ElMessage.success('创建成功')
    showCreateDialog.value = false
    await loadData()
  } catch (error: any) {
    ElMessage.error(`创建失败: ${error.message}`)
  } finally {
    creating.value = false
  }
}

async function handleToggleEnable(row: RotationInstruction) {
  try {
    await rotationApi.updateRotationInstruction(row.id, {
      enabled: row.enabled,
      account_id: store.selectedAccountId || undefined
    })
    ElMessage.success('更新成功')
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`)
    row.enabled = !row.enabled
  }
}

async function handleClear() {
  try {
    await ElMessageBox.confirm('确定要清除所有已完成的指令吗？', '确认清除', {
      type: 'warning'
    })

    await rotationApi.clearRotationInstructions('COMPLETED', store.selectedAccountId || undefined)
    ElMessage.success('清除成功')
    await loadData()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`清除失败: ${error.message}`)
    }
  }
}

function formatDateTime(datetime: string): string {
  if (!datetime) return '-'
  return new Date(datetime).toLocaleString('zh-CN')
}

async function handleImport() {
  if (!importForm.file) {
    ElMessage.warning('请先选择CSV文件')
    return
  }

  try {
    importing.value = true
    uploadPercentage.value = 0
    uploadStatus.value = 'importing'

    const formData = new FormData()
    formData.append('file', importForm.file.raw as File)
    formData.append('mode', importMode.value)

    const response = await fetch('/api/rotation/import', {
      method: 'POST',
      body: formData
    })

    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || '导入失败')
    }

    const result = await response.json()

    ElMessage.success(`导入完成：成功 ${result.data.imported} 条，失败 ${result.data.failed} 条`)

    if (result.data.errors && result.data.errors.length > 0) {
      console.warn('导入错误详情:', result.data.errors)
    }

    uploadPercentage.value = 100
    uploadStatus.value = 'success'
    showImportDialog.value = false

    importForm.file = null
    csvPreview.value = []
    csvHeaders.value = []
    await loadData()
  } catch (error: any) {
    ElMessage.error(`导入失败: ${error.message}`)
    uploadStatus.value = 'failed'
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.rotation {
  padding: 0;
  width: 100%;
}

.el-table {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.status-hint {
  margin-left: 10px;
  color: #e6a23c;
  font-size: 14px;
}
</style>
