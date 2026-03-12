import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import wsManager from './ws'
import './style.css'

const app = createApp(App)
const pinia = createPinia()

// 添加状态持久化插件
pinia.use(piniaPluginPersistedstate)

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia)
app.use(router)
app.use(ElementPlus)

app.mount('#app')

// 初始化WebSocket连接
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const wsUrl = `${protocol}//${window.location.host}/ws`
console.log('Connecting to WebSocket:', wsUrl)
wsManager.connect(wsUrl)
