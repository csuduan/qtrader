import api from './request'

export interface LoginRequest {
  username: string
  password: string
}

// 统一响应格式中的 data 字段
export interface LoginData {
  token: string
  user: {
    user_id: string
    role: string
  }
}

export interface UserInfo {
  user_id: string
  role: string
}

export const authApi = {
  /**
   * 用户登录
   * 返回统一响应中的 data: {token, user}
   */
  login(data: LoginRequest): Promise<LoginData> {
    return api.post('/auth/login', data)
  },

  /**
   * 获取当前用户信息
   */
  getMe(): Promise<UserInfo> {
    return api.get('/auth/me')
  },

  /**
   * 退出登录
   */
  logout(): Promise<{ success: boolean; message: string }> {
    return api.post('/auth/logout')
  }
}
