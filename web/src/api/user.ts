import api from './request'

/**
 * 用户信息
 */
export interface User {
  user_id: string
  username: string
  role: 'admin' | 'trader' | 'guest'
  created_at?: string
  updated_at?: string
}

/**
 * 创建用户请求
 */
export interface CreateUserRequest {
  username: string
  password: string
  role: 'admin' | 'trader' | 'guest'
}

/**
 * 更新用户请求
 */
export interface UpdateUserRequest {
  username?: string
  role?: 'admin' | 'trader' | 'guest'
  password?: string
}

/**
 * 用户管理 API
 */
export const userApi = {
  /**
   * 获取用户列表
   */
  getUsers: async (): Promise<User[]> => {
    return api.get<User[]>('/admin/users')
  },

  /**
   * 创建用户
   */
  createUser: async (data: CreateUserRequest): Promise<User> => {
    return api.post<User>('/admin/users', data)
  },

  /**
   * 更新用户
   */
  updateUser: async (userId: string, data: UpdateUserRequest): Promise<User> => {
    return api.put<User>(`/admin/users/${userId}`, data)
  },

  /**
   * 删除用户
   */
  deleteUser: async (userId: string): Promise<void> => {
    return api.delete(`/admin/users/${userId}`)
  }
}
