import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import AccountCombined from '@/views/AccountCombined.vue'

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
  // 一级菜单：账户（合并账户详情和交易）
  {
    path: '/account',
    name: 'Account',
    component: AccountCombined,
    meta: { title: '账户', showAccountInfo: true }
  },
  // 一级菜单：换仓
  {
    path: '/rotation',
    name: 'Rotation',
    component: () => import('@/views/Rotation.vue'),
    meta: { title: '换仓', showAccountInfo: true }
  },
  // 一级菜单：策略
  {
    path: '/strategy',
    name: 'Strategy',
    component: () => import('@/views/Strategy.vue'),
    meta: { title: '策略', showAccountInfo: true }
  },
  // 一级菜单：行情
  {
    path: '/market',
    name: 'Market',
    component: () => import('@/views/Market.vue'),
    meta: { title: '行情' }
  },
  // 一级菜单：监控
  {
    path: '/alarms',
    name: 'Alarms',
    component: () => import('@/views/admin/AlarmInfo.vue'),
    meta: { title: '监控' }
  },
  // 一级菜单：设置
  {
    path: '/setting',
    name: 'Setting',
    component: () => import('@/views/account/AccountSetting.vue'),
    meta: { title: '设置' }
  },
  // 管理路由（二级菜单，仅admin可见）
  {
    path: '/admin/log',
    name: 'AdminLog',
    component: () => import('@/views/account/LogView.vue'),
    meta: { title: '日志', requiredRole: 'admin', hideHeader: true }
  },
  {
    path: '/admin/system',
    name: 'SystemAdmin',
    component: () => import('@/views/admin/SystemAdmin.vue'),
    meta: { title: '系统', requiredRole: 'admin', hideHeader: true }
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
    path: '/setting',
    redirect: '/account'
  },
  {
    path: '/account/detail',
    redirect: '/account'
  },
  {
    path: '/account/trading',
    redirect: '/account'
  },
  {
    path: '/account/rotation',
    redirect: '/rotation'
  },
  {
    path: '/account/strategy',
    redirect: '/strategy'
  },
  {
    path: '/account/setting',
    redirect: '/setting'
  },
  {
    path: '/account/log',
    redirect: '/admin/log'
  },
  {
    path: '/trading',
    redirect: '/account'
  },
  {
    path: '/rotation',
    redirect: '/rotation'
  },
  {
    path: '/system',
    redirect: '/admin/system'
  },
  {
    path: '/admin/alarms',
    redirect: '/alarms'
  },
  {
    path: '/bars',
    redirect: '/market'
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
