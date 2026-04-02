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
    meta: { title: '总览', hideHeader: true }
  },
  // 账户相关路由（二级菜单）
  {
    path: '/account/detail',
    name: 'AccountDetail',
    component: () => import('@/views/Account.vue'),
    meta: { title: '账户详情' }
  },
  {
    path: '/account/trading',
    name: 'AccountTrading',
    component: () => import('@/views/Trading.vue'),
    meta: { title: '交易' }
  },
  {
    path: '/account/rotation',
    name: 'AccountRotation',
    component: () => import('@/views/Rotation.vue'),
    meta: { title: '换仓' }
  },
  {
    path: '/account/strategy',
    name: 'AccountStrategy',
    component: () => import('@/views/Strategy.vue'),
    meta: { title: '策略' }
  },
  {
    path: '/account/setting',
    name: 'AccountSetting',
    component: () => import('@/views/account/AccountSetting.vue'),
    meta: { title: '账户设置' }
  },
  // 管理路由（二级菜单）
  {
    path: '/admin/system',
    name: 'SystemAdmin',
    component: () => import('@/views/admin/SystemAdmin.vue'),
    meta: { title: '系统管理', hideHeader: true }
  },
  {
    path: '/admin/alarms',
    name: 'AdminAlarms',
    component: () => import('@/views/admin/AlarmInfo.vue'),
    meta: { title: '监控告警', hideHeader: true }
  },
  // 策略详情（保留）
  {
    path: '/strategy/:strategyId',
    name: 'StrategyDetails',
    component: () => import('@/views/StrategyDetails.vue'),
    meta: { title: '策略详情' }
  },
  // 重定向：兼容旧路由
  {
    path: '/account',
    redirect: '/account/detail'
  },
  {
    path: '/trading',
    redirect: '/account/trading'
  },
  {
    path: '/rotation',
    redirect: '/account/rotation'
  },
  {
    path: '/strategy',
    redirect: '/account/strategy'
  },
  {
    path: '/system',
    redirect: '/account/setting'
  },
  {
    path: '/alarms',
    redirect: '/admin/alarms'
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
