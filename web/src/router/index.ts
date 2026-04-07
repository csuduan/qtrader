import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true, standalone: true }
  },
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
  {
    path: '/account/log',
    name: 'AccountLog',
    component: () => import('@/views/account/LogView.vue'),
    meta: { title: '日志' }
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
  
  // 检查登录状态
  const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true'
  const token = localStorage.getItem('token')
  const userRole = localStorage.getItem('userRole') || 'guest'
  
  if (to.meta.public) {
    // 公开页面，直接访问
    next()
  } else if (!isLoggedIn || !token) {
    // 未登录，跳转到登录页
    next('/login')
  } else if (to.meta.requiredRole) {
    // 需要特定角色权限
    const requiredRole = to.meta.requiredRole as string
    if (requiredRole === 'admin' && userRole !== 'admin') {
      // 需要admin权限但当前用户不是admin
      next('/dashboard')
    } else {
      next()
    }
  } else {
    // 已登录，正常访问
    next()
  }
})

export default router
