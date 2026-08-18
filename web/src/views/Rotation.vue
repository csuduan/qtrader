<template>
  <div class="rotation-page">
    <el-tabs v-model="activeTab" class="rotation-tabs">
      <el-tab-pane name="instruction" :disabled="!rotationConfig.enable_instruction_rotation">
        <template #label>
          <span class="tab-label">
            换仓-按交易指令
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
      <el-tab-pane name="target" :disabled="!rotationConfig.enable_target_pos_rotation">
        <template #label>
          <span class="tab-label">
            换仓-按目标仓位
            <el-badge v-if="targetCount > 0" :value="targetCount" :max="99" />
          </span>
        </template>
        <TargetRotationTab
          v-if="activeTab === 'target'"
          @count-update="targetCount = $event"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from "vue";
import { rotationApi, targetPositionApi } from "@/api";
import { systemApi, type RotationConfig } from "@/api/system";
import { useStore } from "@/stores";
import InstructionRotationTab from "./rotation/InstructionRotationTab.vue";
import TargetRotationTab from "./rotation/TargetRotationTab.vue";

const store = useStore();
const activeTab = ref<"instruction" | "target">("instruction");
const instructionCount = ref(0);
const targetCount = ref(0);
// 默认开启，配置加载成功前不置灰，避免页面闪烁
const rotationConfig = ref<RotationConfig>({
  enable_instruction_rotation: true,
  enable_target_pos_rotation: true,
});

/** 拉取换仓开关配置，未开启的换仓 tab 置灰 */
async function loadRotationConfig() {
  const accountId = store.selectedAccountId;
  if (!accountId) return;
  try {
    rotationConfig.value = await systemApi.getRotationConfig(accountId);
  } catch {
    // 配置加载失败保持默认开启
  }
}

/** 当前激活 tab 被关闭时自动切换到仍开启的 tab */
watch(
  () => [rotationConfig.value.enable_instruction_rotation, rotationConfig.value.enable_target_pos_rotation] as const,
  ([instructionEnabled, targetEnabled]) => {
    if (activeTab.value === "instruction" && !instructionEnabled && targetEnabled) {
      activeTab.value = "target";
    } else if (activeTab.value === "target" && !targetEnabled && instructionEnabled) {
      activeTab.value = "instruction";
    }
  }
);

/** 拉取两个换仓列表的记录数，用于 tab 标题徽标提示 */
async function loadCounts() {
  const accountId = store.selectedAccountId || "";
  if (!accountId) return;
  try {
    const [rotationResult, targetResult] = await Promise.all([
      rotationApi.getRotationInstructions(accountId),
      targetPositionApi.getTargetInstructions(accountId),
    ]);
    instructionCount.value = rotationResult.instructions.length;
    targetCount.value = targetResult.instructions.length;
  } catch {
    // 徽标为辅助提示，加载失败静默忽略
  }
}

function loadAll() {
  loadCounts();
  loadRotationConfig();
}

onMounted(loadAll);
watch(() => store.selectedAccountId, loadAll);
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
