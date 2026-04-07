<template>
  <div class="login-page">
    <div class="login-container">
      <div class="login-left">
        <div class="brand">
          <img src="/logo.png" alt="Q-Trader" class="logo" />
          <h1 class="brand-name">Q-Trader</h1>
          <p class="brand-slogan">专业量化交易平台</p>
        </div>
        <div class="features">
          <div class="feature-item">
            <el-icon class="feature-icon"><TrendCharts /></el-icon>
            <div class="feature-text">
              <div class="feature-title">智能策略</div>
              <div class="feature-desc">支持多种量化交易策略</div>
            </div>
          </div>
          <div class="feature-item">
            <el-icon class="feature-icon"><DataLine /></el-icon>
            <div class="feature-text">
              <div class="feature-title">实时监控</div>
              <div class="feature-desc">全天候账户与风控监控</div>
            </div>
          </div>
          <div class="feature-item">
            <el-icon class="feature-icon"><User /></el-icon>
            <div class="feature-text">
              <div class="feature-title">多账户支持</div>
              <div class="feature-desc">统一管理多个交易账户</div>
            </div>
          </div>
        </div>
      </div>
      
      <div class="login-right">
        <div class="login-box">
          <h2 class="login-title">欢迎登录</h2>
          <p class="login-subtitle">请使用您的账户密码登录系统</p>
          
          <el-form
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            class="login-form"
            @keyup.enter="handleLogin"
          >
            <el-form-item prop="username">
              <el-input
                v-model="loginForm.username"
                placeholder="用户名"
                size="large"
                :prefix-icon="User"
                clearable
              />
            </el-form-item>
            
            <el-form-item prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                placeholder="密码"
                size="large"
                :prefix-icon="Lock"
                show-password
                clearable
              />
            </el-form-item>
            
            <div class="login-options">
              <el-checkbox v-model="rememberMe">记住我</el-checkbox>
            </div>
            
            <el-button
              type="primary"
              size="large"
              class="login-btn"
              :loading="loading"
              @click="handleLogin"
            >
              登 录
            </el-button>
          </el-form>
          
          <div class="login-footer">
            <p>© 2024 Q-Trader. All rights reserved.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, TrendCharts, DataLine } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { authApi } from '@/api'

const router = useRouter()
const loginFormRef = ref<FormInstance>()
const loading = ref(false)
const rememberMe = ref(localStorage.getItem('rememberMe') !== 'false')

const loginForm = reactive({
  username: localStorage.getItem('savedUsername') || '',
  password: ''
})

const loginRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度至少6位', trigger: 'blur' }
  ]
}

const handleLogin = async () => {
  if (!loginFormRef.value) return
  
  await loginFormRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      
      try {
        const response = await authApi.login({
          username: loginForm.username,
          password: loginForm.password
        })
        
        // 响应格式: {code: 0, message: "success", data: {token, user}}
        // 经过拦截器后，response 已经是 data 字段
        if (response && response.token) {
          // 保存登录状态
          localStorage.setItem('isLoggedIn', 'true')
          localStorage.setItem('username', response.user?.user_id || loginForm.username)
          localStorage.setItem('userRole', response.user?.role || 'guest')
          localStorage.setItem('token', response.token)
          
          if (rememberMe.value) {
            localStorage.setItem('rememberMe', 'true')
            localStorage.setItem('savedUsername', loginForm.username)
          } else {
            localStorage.setItem('rememberMe', 'false')
            localStorage.removeItem('savedUsername')
          }

          ElMessage.success('登录成功')
          router.push('/dashboard')
        } else {
          ElMessage.error('登录失败')
        }
      } catch (error: any) {
        ElMessage.error(error.message || '登录失败')
      } finally {
        loading.value = false
      }
    }
  })
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  width: 100vw;
  display: flex;
  background: #f5f7fa;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  overflow: hidden;
}

.login-container {
  display: flex;
  width: 100%;
  height: 100%;
}

/* 左侧品牌区域 */
.login-left {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 40px 60px 40px 100px;
  background: linear-gradient(135deg, #304156 0%, #1f2d3d 100%);
  color: white;
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
  position: relative;
  box-sizing: border-box;
}

/* 装饰性背景圆形 */
.login-left::before {
  content: '';
  position: absolute;
  top: -30%;
  right: -10%;
  width: 70%;
  height: 120%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.15) 0%, rgba(255, 255, 255, 0.05) 50%, transparent 70%);
  border-radius: 50%;
}

.login-left::after {
  content: '';
  position: absolute;
  bottom: -30%;
  left: -10%;
  width: 60%;
  height: 100%;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 50%;
}

.brand {
  margin-bottom: 60px;
  text-align: left;
}

.logo {
  width: 80px;
  height: 80px;
  margin-bottom: 24px;
  filter: brightness(0) invert(1);
  display: block;
  margin-left: 60px;
}

.brand-name {
  font-size: 48px;
  font-weight: 700;
  margin: 0 0 12px 0;
  letter-spacing: -1px;
}

.brand-slogan {
  font-size: 20px;
  opacity: 0.9;
  margin: 0;
}

.features {
  display: flex;
  flex-direction: column;
  gap: 32px;
  align-items: flex-start;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.feature-icon {
  font-size: 28px;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 12px;
  backdrop-filter: blur(10px);
}

.feature-text {
  text-align: left;
}

.feature-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 4px;
  text-align: left;
}

.feature-desc {
  font-size: 14px;
  opacity: 0.8;
  text-align: left;
}

/* 右侧登录区域 */
.login-right {
  width: 480px;
  min-width: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: white;
  height: 100%;
  overflow-y: auto;
}

.login-box {
  width: 100%;
  max-width: 360px;
}

.login-title {
  font-size: 32px;
  font-weight: 700;
  color: #1f2937;
  margin: 0 0 8px 0;
}

.login-subtitle {
  font-size: 14px;
  color: #6b7280;
  margin: 0 0 32px 0;
}

.login-form {
  margin-bottom: 24px;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  border: 1px solid #e5e7eb;
}

.login-form :deep(.el-input__wrapper:hover) {
  border-color: #d1d5db;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  border-color: #304156;
  box-shadow: 0 0 0 3px rgba(48, 65, 86, 0.1);
}

.login-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.login-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  border-radius: 8px;
  background: #304156;
  border: none;
  box-shadow: 0 4px 12px rgba(48, 65, 86, 0.4);
  transition: all 0.3s ease;
}

.login-btn:hover {
  background: #1f2d3d;
  box-shadow: 0 6px 16px rgba(48, 65, 86, 0.5);
}

.login-footer {
  text-align: center;
  color: #9ca3af;
  font-size: 12px;
}

/* 响应式 */
@media (max-width: 900px) {
  .login-left {
    display: none;
  }
  
  .login-right {
    width: 100%;
    padding: 24px;
  }
}

@media (max-width: 480px) {
  .login-box {
    max-width: 100%;
  }
  
  .login-title {
    font-size: 28px;
  }
}
</style>
