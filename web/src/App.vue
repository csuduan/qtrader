<template>
  <el-container class="app-container">
    <!-- 侧边栏 -->
    <el-aside width="150px" class="sidebar">
      <div class="logo">
         <img :src="getLogo()" alt="logo" width="40" />
        <h2>Q-Trader</h2>
      </div>
      <el-menu
        :default-active="$route.path"
        router
        class="nav-menu"
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataBoard /></el-icon>
          <span>总览</span>
        </el-menu-item>
        <el-menu-item index="/account">
          <el-icon><User /></el-icon>
          <span>账户</span>
        </el-menu-item>
        <el-menu-item index="/rotation">
          <el-icon><Tickets /></el-icon>
          <span>换仓</span>
        </el-menu-item>
        <el-menu-item index="/system">
          <el-icon><Setting /></el-icon>
          <span>系统</span>
        </el-menu-item>
        <el-menu-item index="/alarms">
          <el-icon><Warning /></el-icon>
          <span>告警</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主体内容 -->
    <el-container class="main-container">
      <!-- 顶部栏 -->
      <el-header class="header">
        <div class="header-left">
          <el-tag :type="store.systemStatus.connected ? 'success' : 'danger'" size="large">
            {{ store.systemStatus.connected ? '已连接' : '未连接' }}
          </el-tag>
          <el-tag v-if="store.systemStatus.connected" :type="store.systemStatus.paused ? 'danger' : 'success'" size="large" class="ml-2">
            {{ store.systemStatus.paused ? '交易暂停' : '交易正常' }}
          </el-tag>
        </div>
        <div class="header-right">
          <div v-if="store.account" class="account-info">
            <span>账户: {{ store.account.account_id }}</span>
            <el-divider direction="vertical" />
            <span>可用: ¥{{ formatNumber(store.account.available) }}</span>
            <el-divider direction="vertical" />
            <span>浮动盈亏: <span :class="store.account.float_profit >= 0 ? 'profit' : 'loss'">¥{{ formatNumber(store.account.float_profit) }}</span></span>
          </div>
        </div>
      </el-header>

      <!-- 主内容区 -->
      <el-main class="main-content">
        <div class="content-wrapper">
          <router-view />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useStore } from '@/stores'
import wsManager from '@/ws'

const store = useStore()

function getLogo() {
    return new URL("/logo.png", import.meta.url).href;
  }
// 格式化数字
function formatNumber(num: number): string {
  return num.toFixed(2)
}

onMounted(async () => {
  // 加载初始数据
  await store.loadAllData()

  // 初始化 WebSocket
  store.initWebSocket()
})

onUnmounted(() => {
  wsManager.disconnect()
})
</script>

<style scoped>
#app {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}

.app-container {
  height: 100vh;
  width: 100vw;
  display: flex;
}

.sidebar {
  background-color: #304156;
  overflow-x: hidden;
}

.logo {
  padding: 30px 20px;
  color: #fff;
  text-align: center;
  border-bottom: 1px solid #1f2d3d;
}

.logo h2 {
  margin: 0 0 10px 0;
  font-size: 20px;
  font-weight: 600;
}

.logo p {
  margin: 0;
  font-size: 12px;
  color: #8391a5;
}

.nav-menu {
  border-right: none;
}

.main-container {
  flex: 1;
  min-width: 0;
}

.header {
  background-color: #fff;
  border-bottom: 1px solid #e6e6e6;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
}

.header-right {
  display: flex;
  align-items: center;
}

.account-info {
  display: flex;
  align-items: center;
  font-size: 14px;
}

.ml-2 {
  margin-left: 8px;
}

.profit {
  color: #67c23a;
  font-weight: 600;
}

.loss {
  color: #f56c6c;
  font-weight: 600;
}

.main-content {
  background-color: #f0f2f5;
  height: calc(100vh - 60px);
  overflow: auto;
}

.content-wrapper {
  width: 100%;
}
</style>
