import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '总览' }
  },
  {
    path: '/account',
    name: 'Account',
    component: () => import('@/views/Account.vue'),
    meta: { title: '账户' }
  },
  {
    path: '/rotation',
    name: 'Rotation',
    component: () => import('@/views/Rotation.vue'),
    meta: { title: '换仓' }
  },
  {
    path: '/system',
    name: 'System',
    component: () => import('@/views/System.vue'),
    meta: { title: '系统' }
  },
  {
    path: '/alarms',
    name: 'Alarms',
    component: () => import('@/views/Alarm.vue'),
    meta: { title: '告警' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach((to, _from, next) => {
  // 设置页面标题
  document.title = `${to.meta.title || ''} | Q-Trader`
  next()
})

export default router
