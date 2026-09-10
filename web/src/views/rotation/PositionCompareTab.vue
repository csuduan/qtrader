<template>
  <div class="position-compare">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <div>
            <span>仓位比对</span>
            <span class="hint">目标仓位文件与当前持仓实时比对，可按偏差导出换仓指令文件</span>
          </div>
          <div class="header-actions">
            <el-button
              @click="handleExport"
              :loading="exporting"
              type="primary"
              :disabled="deviationCount === 0"
            >
              <el-icon><Download /></el-icon>
              导出换仓指令
            </el-button>
            <el-button
              @click="handleExportTargetPositions"
              :loading="exportingPositions"
              type="success"
            >
              <el-icon><Document /></el-icon>
              导出目标仓位
            </el-button>
            <el-button @click="showImportDialog = true">
              <el-icon><Upload /></el-icon>
              导入目标仓位
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
          data-testid="position-compare-table"
          :data="comparisons"
          table-layout="fixed"
          :size="isMobile ? 'small' : 'default'"
        >
          <template #empty>
            <el-empty description="暂无目标仓位文件，请导入或投放目标仓位文件" />
          </template>
          <el-table-column label="合约" :width="isMobile ? 90 : 120">
            <template #default="{ row }">
              {{ row.symbol }}
            </template>
          </el-table-column>
          <el-table-column label="方向" :width="isMobile ? 70 : 80">
            <template #default="{ row }">
              <el-tag :type="row.side === 'LONG' ? 'success' : 'danger'" size="small">
                {{ row.side === "LONG" ? "多头" : "空头" }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="持仓手数" :width="isMobile ? 70 : 90">
            <template #default="{ row }">
              {{ row.current_volume }}
            </template>
          </el-table-column>
          <el-table-column label="目标手数" :width="isMobile ? 80 : 100">
            <template #default="{ row }">
              <div
                v-if="editingKey === rowKey(row)"
                class="edit-cell"
                @click.stop
              >
                <el-input-number
                  v-model="editValue"
                  :controls="false"
                  :min="0"
                  :precision="0"
                  :step="1"
                  size="small"
                  style="width: 100%"
                  @blur="submitEdit(row)"
                  @keyup.enter="submitEdit(row)"
                  @keyup.esc="cancelEdit"
                />
              </div>
              <span v-else class="editable-text" @click="startEdit(row)">
                {{ row.target_volume == null ? "--" : row.target_volume }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="偏差" :width="isMobile ? 70 : 90">
            <template #default="{ row }">
              <span
                :style="{
                  color: deviationColor(row.deviation),
                  fontWeight: 600,
                }"
              >
                {{ deviationText(row.deviation) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column
            v-if="!isMobile"
            prop="source"
            label="来源文件"
            min-width="200"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              {{ row.source || "-" }}
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
        title="CSV格式参考实例（文件名需包含8位交易日与账户ID，如 TargetPos-DQ-20260811.csv）"
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
          说明：Buy=多头目标手数，Sell=空头目标手数；只有出现的侧才会比对，未出现的侧保持不动。文件保存后按当前持仓实时比对。
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
      </el-form>
      <template #footer>
        <el-button @click="showImportDialog = false" :disabled="importing">取消</el-button>
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
import { ref, reactive, computed, watch, onMounted, onUnmounted } from "vue";
import { ElMessage, ElMessageBox, type UploadInstance, type UploadUserFile } from "element-plus";
import { Refresh, Upload, Download, Document } from "@element-plus/icons-vue";
import { targetPositionApi } from "@/api";
import { useStore } from "@/stores";
import type { TargetPositionCompare } from "@/types";

const store = useStore();

const loading = ref(false);
const exporting = ref(false);
const exportingPositions = ref(false);
const comparisons = ref<TargetPositionCompare[]>([]);
const isMobile = ref(false);
const editingKey = ref<string | null>(null);
const editValue = ref<number | null>(null);

const deviationCount = computed(
  () => comparisons.value.filter((r) => (r.volume ?? 0) > 0).length,
);

function rowKey(row: TargetPositionCompare): string {
  return `${row.symbol}-${row.side}`;
}

function startEdit(row: TargetPositionCompare) {
  editingKey.value = rowKey(row);
  editValue.value = row.target_volume;
}

function cancelEdit() {
  editingKey.value = null;
  editValue.value = null;
}

async function submitEdit(row: TargetPositionCompare) {
  if (editingKey.value !== rowKey(row)) {
    return;
  }
  const newValue = editValue.value;
  if (newValue === row.target_volume) {
    cancelEdit();
    return;
  }
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    cancelEdit();
    return;
  }
  try {
    await targetPositionApi.updateTarget(
      store.selectedAccountId,
      row.symbol,
      row.side,
      newValue,
    );
    ElMessage.success("目标手数已更新");
    cancelEdit();
    await loadData();
  } catch (error: any) {
    ElMessage.error(`更新目标手数失败: ${error.message}`);
    cancelEdit();
  }
}

const updateIsMobile = () => {
  isMobile.value = window.innerWidth <= 768;
};

function deviationColor(dev: number | null): string {
  if (dev == null) return "#909399";
  if (dev > 0) return "#e6a23c";
  if (dev < 0) return "#f56c6c";
  return "#909399";
}

function deviationText(dev: number | null): string {
  if (dev == null) return "--";
  return dev > 0 ? `+${dev}` : `${dev}`;
}

function downloadBase64File(base64: string, fileName: string, _encoding?: string) {
  const byteCharacters = atob(base64);
  const byteNumbers = new Array(byteCharacters.length);
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i);
  }
  const byteArray = new Uint8Array(byteNumbers);
  const blob = new Blob([byteArray], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

async function loadData() {
  loading.value = true;
  try {
    const result = await targetPositionApi.getComparison(store.selectedAccountId || "");
    comparisons.value = result.comparisons;
  } catch (error: any) {
    ElMessage.error(`加载仓位比对失败: ${error.message}`);
  } finally {
    loading.value = false;
  }
}

async function handleExport() {
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    return;
  }
  try {
    await ElMessageBox.confirm(
      `确定要按当前偏差导出换仓指令文件吗？共 ${deviationCount.value} 条指令，` +
        "文件将写入换仓指令目录并由指令换仓流程自动导入执行。",
      "确认导出",
      { type: "warning" },
    );
    exporting.value = true;
    const result = await targetPositionApi.exportInstructions(store.selectedAccountId);
    if (result.exported > 0) {
      ElMessage.success(`已导出 ${result.exported} 条换仓指令：${result.file_name}`);
      if (result.content_base64 && result.file_name) {
        downloadBase64File(result.content_base64, result.file_name, result.encoding);
      }
    } else {
      ElMessage.info("目标仓位与持仓无偏差，未生成指令文件");
    }
    await loadData();
  } catch (error: any) {
    if (error !== "cancel") {
      ElMessage.error(`导出换仓指令失败: ${error.message}`);
    }
  } finally {
    exporting.value = false;
  }
}

async function handleExportTargetPositions() {
  if (!store.selectedAccountId) {
    ElMessage.error("请先选择账户");
    return;
  }
  try {
    await ElMessageBox.confirm(
      "确定要将当前账户所有持仓导出为目标仓位文件吗？默认导出全部持仓（多空两侧分别一行）。",
      "确认导出目标仓位",
      { type: "warning" },
    );
    exportingPositions.value = true;
    const result = await targetPositionApi.exportTargetPositions(store.selectedAccountId);
    if (result.exported > 0) {
      ElMessage.success(`已导出 ${result.exported} 条目标仓位：${result.file_name}`);
      if (result.content_base64 && result.file_name) {
        downloadBase64File(result.content_base64, result.file_name, result.encoding);
      }
    } else {
      ElMessage.info("当前账户无持仓，未导出目标仓位文件");
    }
    await loadData();
  } catch (error: any) {
    if (error !== "cancel") {
      ElMessage.error(`导出目标仓位失败: ${error.message}`);
    }
  } finally {
    exportingPositions.value = false;
  }
}

// ==================== 导入目标仓位文件 ====================
const showImportDialog = ref(false);
const importing = ref(false);
const uploadRef = ref<UploadInstance>();
const csvPreview = ref<Record<string, string>[]>([]);
const csvHeaders = ref<string[]>([]);
const importForm = reactive({ file: null as UploadUserFile | null });

function handleDialogOpen() {
  uploadRef.value?.clearFiles();
  importForm.file = null;
  csvPreview.value = [];
  csvHeaders.value = [];
}

function handleFileRemove() {
  importForm.file = null;
  csvPreview.value = [];
  csvHeaders.value = [];
}

const handleFileChange = (file: UploadUserFile) => {
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

    const formData = new FormData();
    formData.append("file", importForm.file.raw as File);

    await targetPositionApi.importTarget(formData, store.selectedAccountId);

    ElMessage.success("目标仓位文件已保存，比对结果已更新");
    showImportDialog.value = false;

    importForm.file = null;
    csvPreview.value = [];
    csvHeaders.value = [];
    await loadData();
  } catch (error: any) {
    ElMessage.error(`导入失败: ${error.message}`);
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
});
</script>

<style scoped>
.position-compare {
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

.editable-text {
  cursor: pointer;
  color: #409eff;
}

.edit-cell {
  width: 100%;
}
</style>
