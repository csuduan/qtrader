<template>
  <div class="target-rotation">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <div>
            <span>目标仓位管理</span>
            <span class="hint">按目标持仓与账户持仓的偏差自动下单</span>
          </div>
          <div class="header-actions">
            <el-tag
              v-if="rotationStatus.working"
              type="success"
              size="large"
              style="margin-right: 10px"
            >
              目标换仓中
            </el-tag>
            <el-button
              v-if="!rotationStatus.working"
              @click="handleStart"
              :loading="rotating"
              type="success"
            >
              <el-icon><VideoPlay /></el-icon>
              开始换仓
            </el-button>
            <el-button
              v-else
              @click="handleStop"
              :loading="stopping"
              type="danger"
            >
              <el-icon><CircleClose /></el-icon>
              停止换仓
            </el-button>
            <el-button
              @click="showImportDialog = true"
              :disabled="rotationStatus.working"
            >
              <el-icon><Upload /></el-icon>
              导入目标仓位
            </el-button>
            <el-button
              @click="handleBatchDelete"
              :loading="batchDeleting"
              :disabled="selectedRows.length === 0 || rotationStatus.working"
              type="danger"
            >
              <el-icon><Delete /></el-icon>
              删除选中
            </el-button>
            <el-button @click="loadData" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <div class="table-wrapper">
        <el-table
          :data="instructions"
          :row-class-name="tableRowClassName"
          table-layout="fixed"
          :size="isMobile ? 'small' : 'default'"
          @selection-change="handleSelectionChange"
        >
          <template #empty>
            <el-empty description="暂无目标仓位差值指令，请导入目标仓位文件" />
          </template>
          <el-table-column type="selection" width="45" />
          <el-table-column label="合约" :width="isMobile ? 90 : 110">
            <template #default="{ row }">
              {{ row.symbol }}
            </template>
          </el-table-column>
          <el-table-column label="方向" :width="isMobile ? 70 : 90">
            <template #default="{ row }">
              <el-tag
                :type="row.side === 'LONG' ? 'success' : 'danger'"
                size="small"
              >
                {{ row.side === "LONG" ? "多头" : "空头" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="持仓手数" :width="isMobile ? 70 : 90">
            <template #default="{ row }">
              {{ row.current_volume == null ? "-" : row.current_volume }}
            </template>
          </el-table-column>
          <el-table-column label="目标手数" :width="isMobile ? 100 : 120">
            <template #default="{ row }">
              <div v-if="editingId === row.id" class="target-edit">
                <el-input-number
                  v-model="editingVolume"
                  :min="0"
                  size="small"
                  controls-position="right"
                  style="width: 90px"
                />
                <el-icon
                  class="edit-btn confirm"
                  :class="{ 'is-loading': savingVolume }"
                  @click="saveTargetVolume(row)"
                >
                  <Check />
                </el-icon>
                <el-icon class="edit-btn cancel" @click="cancelEditTarget">
                  <Close />
                </el-icon>
              </div>
              <div v-else class="target-volume-cell">
                <span>{{ row.target_volume }}</span>
                <el-icon
                  v-if="!rotationStatus.working"
                  class="edit-icon"
                  title="编辑目标手数"
                  @click="startEditTarget(row)"
                >
                  <Edit />
                </el-icon>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="当前偏差" :width="isMobile ? 80 : 100">
            <template #default="{ row }">
              <span
                :style="{
                  color: deviationColor(row.current_deviation),
                  fontWeight: 600,
                }"
              >
                {{ deviationText(row.current_deviation) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="进度" :width="isMobile ? 120 : 160">
            <template #default="{ row }">
              <el-progress
                :percentage="getProgress(row)"
                :format="() => `${row.filled_volume}/${row.volume}`"
              />
              <div
                v-if="row.pending_volume > 0"
                style="font-size: 11px; color: #e6a23c; margin-top: 2px"
              >
                进行中: {{ row.pending_volume }} 手
              </div>
            </template>
          </el-table-column>
          <el-table-column
            label="信息"
            show-overflow-tooltip
            :min-width="isMobile ? 80 : 120"
          >
            <template #default="{ row }">
              <span v-if="!row.enabled" style="color: #909399">已禁用</span>
              <span
                v-else-if="row.status === 'COMPLETED'"
                style="color: #67c23a"
                >已完成</span
              >
              <span v-else-if="row.status === 'PENDING'" style="color: #909399"
                >待执行</span
              >
              <span v-else-if="row.status === 'RUNNING'" style="color: #e6a23c"
                >执行中</span
              >
              <span v-else style="color: #f56c6c">{{
                row.error_message || "失败"
              }}</span>
            </template>
          </el-table-column>
          <el-table-column label="启用" :width="isMobile ? 60 : 70">
            <template #default="{ row }">
              <el-switch
                v-model="row.enabled"
                :disabled="rotationStatus.working"
                @change="handleToggleEnable(row)"
              />
            </template>
          </el-table-column>
          <el-table-column
            v-if="!isMobile"
            prop="source"
            label="来源"
            width="160"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              {{ row.source || "-" }}
            </template>
          </el-table-column>
          <el-table-column
            v-if="!isMobile"
            prop="updated_at"
            label="更新时间"
            width="180"
          >
            <template #default="{ row }">
              {{ formatDateTime(row.updated_at) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 导入目标仓位 CSV 对话框 -->
    <el-dialog
      v-model="showImportDialog"
      title="导入目标仓位 CSV"
      width="90%"
      style="max-width: 700px"
      @open="handleDialogOpen"
    >
      <el-alert
        title="CSV格式参考实例（文件名需包含8位交易日，如 TargetPos-DQ-20260811.csv）"
        type="info"
        :closable="false"
        style="margin-bottom: 15px"
      >
        <div
          style="
            font-size: 12px;
            line-height: 1.8;
            font-family: monospace;
            background: #f5f7fa;
            padding: 10px;
            border-radius: 4px;
          "
        >
          account,stragegy,symbol,direction,volume<br />
          DQ,StrategyFix_A,A2611,Sell,2<br />
          DQ,StrategyFix_AL,AL2609,Buy,6
        </div>
        <div style="font-size: 12px; color: #909399; margin-top: 6px">
          说明：Buy=多头目标手数，Sell=空头目标手数；只有出现的侧才会调整，未出现的侧保持不动。重复导入会按当前持仓重新计算差值。
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
          <div class="table-wrapper">
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
          </div>
        </el-form-item>

        <el-progress
          v-if="importing"
          :percentage="uploadPercentage"
          :status="uploadStatus"
        >
          正在导入 {{ uploadPercentage }}%
        </el-progress>
      </el-form>
      <template #footer>
        <el-button @click="showImportDialog = false" :disabled="importing"
          >取消</el-button
        >
        <el-button
          type="primary"
          @click="handleImport"
          :loading="importing"
          :disabled="csvPreview.length === 0"
        >
          确认导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted, onUnmounted } from "vue";
import {
  ElMessage,
  ElMessageBox,
  type UploadInstance,
  type UploadUserFile,
} from "element-plus";
import {
  VideoPlay,
  Refresh,
  Upload,
  CircleClose,
  Delete,
  Edit,
  Check,
  Close,
} from "@element-plus/icons-vue";
import { targetPositionApi } from "@/api";
import { useStore } from "@/stores";
import type { TargetPosInstruction } from "@/types";

const store = useStore();

const emit = defineEmits<{ (e: "count-update", count: number): void }>();

const loading = ref(false);
const rotating = ref(false);
const stopping = ref(false);
const batchDeleting = ref(false);
const showImportDialog = ref(false);
const importing = ref(false);
const uploadPercentage = ref(0);
const uploadStatus = ref("");
const uploadRef = ref<UploadInstance>();
const instructions = ref<TargetPosInstruction[]>([]);
const selectedRows = ref<TargetPosInstruction[]>([]);
const rotationStatus = reactive({ working: false, is_manual: false });
const csvPreview = ref<Record<string, string>[]>([]);
const csvHeaders = ref<string[]>([]);
const importForm = reactive({ file: null as UploadUserFile | null });
const isMobile = ref(false);
const pollInterval = ref<number | null>(null);

void uploadRef;

const tableRowClassName = ({ row }: { row: TargetPosInstruction }) => {
  return row.enabled ? "" : "disabled-row";
};

function handleSelectionChange(selection: TargetPosInstruction[]) {
  selectedRows.value = selection;
}

async function handleBatchDelete() {
  if (selectedRows.value.length === 0) {
    ElMessage.warning("请先选择要删除的指令");
    return;
  }
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    return;
  }
  try {
    await ElMessageBox.confirm(
      `确定要删除 ${selectedRows.value.length} 条目标仓位指令吗？`,
      "确认删除",
      { type: "warning" },
    );
    batchDeleting.value = true;
    const ids = selectedRows.value.map((r) => r.id);
    const result = await targetPositionApi.batchDeleteInstructions(
      ids,
      store.selectedAccountId,
    );
    ElMessage.success(`删除成功，共 ${result.deleted} 条`);
    selectedRows.value = [];
    await loadData();
  } catch (error: any) {
    if (error !== "cancel") {
      ElMessage.error(`删除失败: ${error.message}`);
    }
  } finally {
    batchDeleting.value = false;
  }
}

async function handleToggleEnable(row: TargetPosInstruction) {
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    row.enabled = !row.enabled;
    return;
  }
  try {
    await targetPositionApi.updateInstruction(
      row.id,
      { enabled: row.enabled },
      store.selectedAccountId,
    );
    ElMessage.success(row.enabled ? "已启用" : "已禁用");
  } catch (error: any) {
    ElMessage.error(`操作失败: ${error.message}`);
    row.enabled = !row.enabled;
  }
}

// 目标手数行内编辑
const editingId = ref<number | null>(null);
const editingVolume = ref(0);
const savingVolume = ref(false);

function startEditTarget(row: TargetPosInstruction) {
  editingId.value = row.id;
  editingVolume.value = row.target_volume;
}

function cancelEditTarget() {
  editingId.value = null;
}

async function saveTargetVolume(row: TargetPosInstruction) {
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    return;
  }
  if (editingVolume.value === row.target_volume) {
    cancelEditTarget();
    return;
  }
  try {
    savingVolume.value = true;
    await targetPositionApi.updateInstruction(
      row.id,
      { target_volume: editingVolume.value },
      store.selectedAccountId,
    );
    ElMessage.success("目标手数已更新");
    editingId.value = null;
    await loadData();
  } catch (error: any) {
    ElMessage.error(`更新目标手数失败: ${error.message}`);
  } finally {
    savingVolume.value = false;
  }
}

const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 768;
};

function getProgress(row: TargetPosInstruction): number {
  // 进度 = 本次累计成交 / 本轮需要成交手数
  // 新一轮换仓开始时后端重置：filled_volume=0、volume=当前偏差
  if (!row.volume) return 0;
  const pct = (row.filled_volume / row.volume) * 100;
  return Math.round(Math.max(0, Math.min(100, pct)));
}

function deviationColor(dev: number | null | undefined): string {
  if (dev == null) return "#909399";
  if (dev > 0) return "#e6a23c";
  if (dev < 0) return "#f56c6c";
  return "#909399";
}

function deviationText(dev: number | null | undefined): string {
  if (dev == null) return "-";
  return dev > 0 ? `+${dev}` : `${dev}`;
}

function formatDateTime(datetime: string): string {
  if (!datetime) return "-";
  return new Date(datetime).toLocaleString("zh-CN");
}

async function loadData() {
  loading.value = true;
  try {
    const result = await targetPositionApi.getTargetInstructions(
      store.selectedAccountId || "",
    );
    instructions.value = result.instructions;
    emit("count-update", instructions.value.length);
    Object.assign(rotationStatus, result.rotation_status);
    if (rotationStatus.working && !pollInterval.value) {
      startPolling();
    } else if (!rotationStatus.working && pollInterval.value) {
      stopPolling();
    }
  } catch (error: any) {
    ElMessage.error(`加载目标仓位指令失败: ${error.message}`);
  } finally {
    loading.value = false;
  }
}

function startPolling() {
  if (pollInterval.value) return;
  pollInterval.value = window.setInterval(async () => {
    await loadData();
    if (!rotationStatus.working) {
      stopPolling();
    }
  }, 2000);
}

function stopPolling() {
  if (pollInterval.value) {
    clearInterval(pollInterval.value);
    pollInterval.value = null;
  }
}

async function handleStart() {
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    return;
  }
  try {
    await ElMessageBox.confirm(
      "确定要根据目标仓位开始换仓吗？将按差值自动下单。",
      "确认目标换仓",
      { type: "warning" },
    );
    rotating.value = true;
    await targetPositionApi.executeTarget(store.selectedAccountId);
    ElMessage.success("目标仓位换仓已启动，正在执行...");
    await loadData();
    startPolling();
  } catch (error: any) {
    if (error !== "cancel") {
      ElMessage.error(`启动目标换仓失败: ${error.message}`);
    }
  } finally {
    rotating.value = false;
  }
}

async function handleStop() {
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    return;
  }
  try {
    await ElMessageBox.confirm(
      "确定要停止目标仓位换仓吗？当前挂单将被撤单。",
      "确认停止",
      {
        type: "warning",
      },
    );
    stopping.value = true;
    await targetPositionApi.stopTarget(store.selectedAccountId);
    ElMessage.success("目标仓位换仓已停止");
    await loadData();
    stopPolling();
  } catch (error: any) {
    if (error !== "cancel") {
      ElMessage.error(`停止目标换仓失败: ${error.message}`);
    }
  } finally {
    stopping.value = false;
  }
}

function handleDialogOpen() {
  uploadRef.value?.clearFiles();
  importForm.file = null;
  csvPreview.value = [];
  csvHeaders.value = [];
  uploadPercentage.value = 0;
  uploadStatus.value = "";
}

function handleFileRemove() {
  importForm.file = null;
  csvPreview.value = [];
  csvHeaders.value = [];
}

const handleFileChange = (file: UploadUserFile) => {
  uploadPercentage.value = 0;
  uploadStatus.value = "uploading";
  importForm.file = file;

  const reader = new FileReader();
  reader.onload = (e: ProgressEvent<FileReader>) => {
    try {
      const text = e.target?.result as string;
      const lines = text.split("\n");

      if (lines.length > 0 && lines[0]) {
        const header = lines[0].trim().split(",");
        csvHeaders.value = header;

        const previewData: Record<string, string>[] = [];
        const previewLines = lines.slice(1, 6);

        for (let i = 0; i < previewLines.length; i++) {
          const line = previewLines[i];
          if (!line) continue;

          const values = line.trim().split(",");
          const row: Record<string, string> = {};

          header.forEach((_, index) => {
            row[`col${index}`] = values[index] || "";
          });

          if (values.length > 0 && values[0]) {
            previewData.push(row);
          }
        }

        csvPreview.value = previewData;
      }

      ElMessage.success(`文件已解析，共 ${lines.length - 1} 行数据`);
    } catch (error: any) {
      ElMessage.error(`解析CSV失败: ${error.message}`);
    }
  };

  reader.readAsText(file.raw as File, "UTF-8");
};

async function handleImport() {
  if (!importForm.file) {
    ElMessage.warning("请先选择CSV文件");
    return;
  }
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    return;
  }

  try {
    importing.value = true;
    uploadPercentage.value = 0;
    uploadStatus.value = "importing";

    const formData = new FormData();
    formData.append("file", importForm.file.raw as File);

    const result = await targetPositionApi.importTarget(
      formData,
      store.selectedAccountId,
    );

    if (result.skipped) {
      ElMessage.info(
        `文件未变化，已跳过导入${result.reason ? `：${result.reason}` : ""}`,
      );
    } else {
      ElMessage.success(`导入完成：生成 ${result.imported} 条差值指令`);
    }

    if (result.errors && result.errors.length > 0) {
      console.warn("导入错误详情:", result.errors);
    }

    uploadPercentage.value = 100;
    uploadStatus.value = "success";
    showImportDialog.value = false;

    importForm.file = null;
    csvPreview.value = [];
    csvHeaders.value = [];
    await loadData();
  } catch (error: any) {
    ElMessage.error(`导入失败: ${error.message}`);
    uploadStatus.value = "failed";
  } finally {
    importing.value = false;
  }
}

watch(
  () => store.selectedAccountId,
  (newId) => {
    if (newId) {
      loadData();
    }
  },
);

onMounted(() => {
  updateIsMobile();
  window.addEventListener("resize", updateIsMobile);
  loadData();
});

onUnmounted(() => {
  window.removeEventListener("resize", updateIsMobile);
  stopPolling();
});
</script>

<style scoped>
.target-rotation {
  padding: 0;
  width: 100%;
}

.el-table {
  width: 100%;
}

.table-wrapper {
  width: 100%;
  overflow-x: auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hint {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .card-header {
    flex-direction: column;
    align-items: stretch;
  }

  .header-actions {
    justify-content: flex-start;
    width: 100%;
  }

  .header-actions .el-button {
    flex: 1;
    min-width: 0;
    padding: 8px 12px;
  }

  .header-actions .el-button span {
    font-size: 12px;
  }
}

.target-rotation :deep(.disabled-row) {
  color: #c0c4cc;
  opacity: 0.6;
}

/* 目标手数行内编辑 */
.target-volume-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.target-volume-cell .edit-icon {
  color: #909399;
  cursor: pointer;
  font-size: 13px;
  visibility: hidden;
}

.target-volume-cell:hover .edit-icon {
  visibility: visible;
}

.target-volume-cell .edit-icon:hover {
  color: #409eff;
}

.target-edit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.target-edit .edit-btn {
  cursor: pointer;
  font-size: 15px;
}

.target-edit .edit-btn.confirm {
  color: #67c23a;
}

.target-edit .edit-btn.confirm.is-loading {
  animation: rotating 1s linear infinite;
  cursor: not-allowed;
}

.target-edit .edit-btn.cancel {
  color: #f56c6c;
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
