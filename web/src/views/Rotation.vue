<template>
  <div class="rotation-page">
    <el-tabs v-model="activeTab" class="rotation-tabs">
      <el-tab-pane name="instruction">
        <template #label>
          <span class="tab-label">
            换仓管理
            <el-badge
              v-if="instructionCount > 0"
              :value="instructionCount"
              :max="99"
            />
          </span>
        </template>
        <InstructionRotationTab
          v-if="activeTab === 'instruction'"
          @count-update="instructionCount = $event"
        />
      </el-tab-pane>
      <el-tab-pane name="compare">
        <template #label>
          <span class="tab-label">
            仓位比对
          </span>
        </template>
        <PositionCompareTab
          v-if="activeTab === 'compare'"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from "vue";
import { rotationApi } from "@/api";
import { useStore } from "@/stores";
import InstructionRotationTab from "./rotation/InstructionRotationTab.vue";
import PositionCompareTab from "./rotation/PositionCompareTab.vue";

const store = useStore();
const activeTab = ref<"instruction" | "compare">("instruction");
const instructionCount = ref(0);

/** 拉取指令换仓列表记录数，用于 tab 标题徽标提示 */
async function loadCounts() {
  const accountId = store.selectedAccountId || "";
  if (!accountId) return;
  try {
    const rotationResult = await rotationApi.getRotationInstructions(accountId);
    instructionCount.value = rotationResult.instructions.length;
  } catch {
    // 徽标为辅助提示，加载失败静默忽略
  }
}

onMounted(loadCounts);
watch(() => store.selectedAccountId, loadCounts);
</script>

<style scoped>
.rotation-page {
  width: 100%;
}

.rotation-tabs {
  width: 100%;
}

/* 让 tab 内容撑满宽度 */
.rotation-tabs :deep(.el-tabs__content) {
  width: 100%;
}

/* tab 标题中的记录数徽标：小号、跟随文字 */
.tab-label {
  display: inline-flex;
  align-items: center;
}

.tab-label :deep(.el-badge__content) {
  position: static;
  transform: none;
  margin-left: 5px;
  height: 13px;
  line-height: 13px;
  padding: 0 4px;
  font-size: 9px;
}
</style>
