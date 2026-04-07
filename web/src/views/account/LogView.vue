<template>
  <div class="log-view">
    <el-card class="log-card" :body-style="{ padding: 0 }">
      <template #header>
        <div class="card-header">
          <span>日志查看</span>
          <div class="header-actions">
            <el-select
              v-model="selectedAccountId"
              size="small"
              style="width: 120px"
              placeholder="选择账户"
              @change="handleAccountChange"
            >
              <el-option
                v-for="account in accountList"
                :key="account"
                :label="account"
                :value="account"
              />
            </el-select>
            <el-select
              v-model="selectedFile"
              size="small"
              style="width: 200px"
              @change="handleFileChange"
            >
              <el-option
                v-for="file in logFiles"
                :key="file.name"
                :label="file.name"
                :value="file.name"
              />
            </el-select>
            <el-switch
              v-model="autoScroll"
              size="small"
              active-text="自动滚动"
            />
            <el-button
              size="small"
              type="primary"
              @click="handleRefresh"
              :loading="loading"
            >
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <el-button
              size="small"
              @click="handleDownload"
              :disabled="!selectedFile"
            >
              <el-icon><Download /></el-icon>
              下载
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="handleClear"
            >
              <el-icon><Delete /></el-icon>
              清空
            </el-button>
          </div>
        </div>
      </template>

      <div
        ref="logContainer"
        class="log-container"
        @scroll="handleScroll"
      >
        <div
          v-for="(line, index) in logLines"
          :key="index"
          class="log-line"
          :class="getLogLevelClass(line)"
        >
          <span class="line-number">{{ index + 1 }}</span>
          <span class="line-content">{{ line }}</span>
        </div>
        <div v-if="logLines.length === 0" class="empty-tip">
          暂无日志内容
        </div>
      </div>

      <div class="status-bar">
        <span>账户: {{ selectedAccountId || '-' }}</span>
        <span>行数: {{ logLines.length }}</span>
        <span>文件大小: {{ formatFileSize(fileSize) }}</span>
        <span v-if="loading">加载中...</span>
        <span v-else-if="!hasMore">已加载全部</span>
        <span v-else>还有更多内容</span>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Download, Delete } from '@element-plus/icons-vue'
import { logApi, type LogFile } from '@/api/log'
import { useStore } from '@/stores'

const store = useStore()

// 账户列表
const accountList = computed(() => store.accounts.map(a => a.account_id))

// 独立选择的账户ID（默认使用store中的当前账户）
const selectedAccountId = ref<string | undefined>('')

const logContainer = ref<HTMLElement | null>(null)
const logLines = ref<string[]>([])
const logFiles = ref<LogFile[]>([])
const selectedFile = ref('')
const offset = ref(0)
const hasMore = ref(true)
const fileSize = ref(0)
const autoScroll = ref(true)
const loading = ref(false)
const userScrolling = ref(false)
const scrollTimeout = ref<number | null>(null)

// 轮询定时器
let pollTimer: number | null = null

// 初始化账户选择
const initAccount = () => {
  // 如果还没有选择账户，使用store中的当前账户或第一个账户
  if (!selectedAccountId.value) {
    if (store.selectedAccountId) {
      selectedAccountId.value = store.selectedAccountId
    } else {
      const firstAccount = accountList.value[0]
      if (firstAccount) {
        selectedAccountId.value = firstAccount
      }
    }
  }
}

// 获取日志文件列表
const fetchLogFiles = async () => {
  const accountId = selectedAccountId.value
  if (!accountId) return
  try {
    const res = await logApi.getLogFiles(accountId)
    logFiles.value = res.files || []
    const firstFile = logFiles.value[0]
    if (firstFile && !selectedFile.value) {
      selectedFile.value = firstFile.name
      await fetchLogContent(true)
    }
  } catch (error) {
    ElMessage.error('获取日志文件列表失败')
  }
}

// 获取日志内容
const fetchLogContent = async (reset = false) => {
  if (!selectedAccountId.value || !selectedFile.value) return
  if (loading.value) return

  loading.value = true
  try {
    if (reset) {
      offset.value = 0
      logLines.value = []
    }

    const res = await logApi.getLog(
      selectedAccountId.value,
      selectedFile.value.replace(`trader-${selectedAccountId.value}_`, '').replace('.log', ''),
      offset.value,
      1000
    )

    if (res.lines.length > 0) {
      logLines.value.push(...res.lines)
      offset.value = res.offset
      hasMore.value = res.has_more
      fileSize.value = res.file_size

      if (autoScroll.value && !userScrolling.value) {
        nextTick(() => {
          scrollToBottom()
        })
      }
    }
  } catch (error) {
    ElMessage.error('获取日志内容失败')
  } finally {
    loading.value = false
  }
}

// 滚动到底部
const scrollToBottom = () => {
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
}

// 处理滚动事件
const handleScroll = () => {
  if (!logContainer.value) return

  userScrolling.value = true

  // 检测是否在底部
  const { scrollTop, scrollHeight, clientHeight } = logContainer.value
  const isAtBottom = scrollHeight - scrollTop - clientHeight < 50

  if (isAtBottom) {
    userScrolling.value = false
  }

  // 清除之前的定时器
  if (scrollTimeout.value) {
    clearTimeout(scrollTimeout.value)
  }

  // 3秒后恢复自动滚动
  scrollTimeout.value = window.setTimeout(() => {
    userScrolling.value = false
  }, 3000)
}

// 轮询获取新日志
const pollLog = async () => {
  if (!selectedAccountId.value || !selectedFile.value) return
  if (userScrolling.value) return

  try {
    const res = await logApi.getLog(
      selectedAccountId.value,
      selectedFile.value.replace(`trader-${selectedAccountId.value}_`, '').replace('.log', ''),
      offset.value,
      1000
    )

    if (res.lines.length > 0) {
      logLines.value.push(...res.lines)
      offset.value = res.offset
      hasMore.value = res.has_more
      fileSize.value = res.file_size

      // 限制最大行数，防止内存溢出
      if (logLines.value.length > 10000) {
        logLines.value = logLines.value.slice(-5000)
      }

      if (autoScroll.value) {
        nextTick(() => {
          scrollToBottom()
        })
      }
    }
  } catch (error) {
    // 静默处理轮询错误
  }
}

// 处理账户切换
const handleAccountChange = () => {
  selectedFile.value = ''
  logLines.value = []
  offset.value = 0
  fetchLogFiles()
}

// 处理文件切换
const handleFileChange = () => {
  fetchLogContent(true)
}

// 手动刷新
const handleRefresh = () => {
  fetchLogContent(true)
}

// 下载日志
const handleDownload = async () => {
  if (!selectedAccountId.value || !selectedFile.value) return

  try {
    const res = await logApi.downloadLog(
      selectedAccountId.value,
      selectedFile.value.replace(`trader-${selectedAccountId.value}_`, '').replace('.log', '')
    )

    // 创建下载链接
    const blob = new Blob([res.content], { type: 'text/plain' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = res.filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    ElMessage.success('下载成功')
  } catch (error) {
    ElMessage.error('下载失败')
  }
}

// 清空日志显示
const handleClear = () => {
  ElMessageBox.confirm('确定要清空当前日志显示吗？', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    logLines.value = []
    offset.value = 0
    ElMessage.success('已清空')
  }).catch(() => {})
}

// 获取日志级别样式类
const getLogLevelClass = (line: string): string => {
  const upperLine = line.toUpperCase()
  if (upperLine.includes('ERROR') || upperLine.includes('CRITICAL')) {
    return 'log-error'
  }
  if (upperLine.includes('WARNING') || upperLine.includes('WARN')) {
    return 'log-warning'
  }
  if (upperLine.includes('INFO')) {
    return 'log-info'
  }
  if (upperLine.includes('DEBUG')) {
    return 'log-debug'
  }
  return ''
}

// 格式化文件大小
const formatFileSize = (size: number): string => {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(2)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(2)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

onMounted(() => {
  // 初始化账户选择
  initAccount()
  // 加载日志文件
  if (selectedAccountId.value) {
    fetchLogFiles()
  }
  // 每3秒轮询一次
  pollTimer = window.setInterval(pollLog, 3000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
  }
  if (scrollTimeout.value) {
    clearTimeout(scrollTimeout.value)
  }
})

// 监听账户列表变化（初始化时可能还没加载完）
watch(accountList, (newList) => {
  const firstAccount = newList[0]
  if (firstAccount && !selectedAccountId.value) {
    selectedAccountId.value = firstAccount
    fetchLogFiles()
  }
})

// 监听自动滚动开关
watch(autoScroll, (value) => {
  if (value) {
    nextTick(() => {
      scrollToBottom()
    })
  }
})
</script>

<style scoped lang="scss">
.log-view {
  padding: 20px;
  height: calc(100vh - 120px);
}

.log-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.log-container {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  background-color: #1e1e1e;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  min-height: 400px;
  max-height: calc(100vh - 220px);
}

.log-line {
  display: flex;
  white-space: pre-wrap;
  word-break: break-all;
  padding: 1px 0;
  color: #d4d4d4;
}

.line-number {
  min-width: 50px;
  text-align: right;
  padding-right: 10px;
  color: #858585;
  user-select: none;
}

.line-content {
  flex: 1;
  text-align: left;
}

.log-error {
  color: #f48771;
  background-color: rgba(244, 135, 113, 0.1);
}

.log-warning {
  color: #dcdcaa;
  background-color: rgba(220, 220, 170, 0.1);
}

.log-info {
  color: #4fc1ff;
}

.log-debug {
  color: #808080;
}

.empty-tip {
  text-align: center;
  color: #858585;
  padding: 50px;
}

.status-bar {
  padding: 8px 15px;
  background-color: #f5f7fa;
  border-top: 1px solid #e4e7ed;
  font-size: 12px;
  color: #606266;
  display: flex;
  gap: 20px;
}
</style>
