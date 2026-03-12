import axios, { type AxiosRequestConfig, type InternalAxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

// 定义响应类型
export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// 自定义Axios类型，拦截器自动解包data
type ApiInstance = {
  get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
  post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  patch<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
}

const axiosInstance = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
axiosInstance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 自动解包 data
axiosInstance.interceptors.response.use(
  (response: AxiosResponse<ApiResponse<any>>) => {
    const res = response.data
    if (res.code === 0) {
      return res.data
    } else {
      const error = new Error(res.message || '请求失败')
      console.error('API Error:', error)
      throw error
    }
  },
  (error) => {
    console.error('Network Error:', error)
    if (error.response) {
      if (error.response.status === 500) {
        ElMessage.error('无法连接服务端')
        throw new Error('无法连接服务端')
      }
      if (error.response.data) {
        const errData = error.response.data as ApiResponse<any>
        throw new Error(errData.message || '请求失败')
      }
    }
    throw new Error('网络请求失败')
  }
)

// 类型断言，确保返回类型正确
const api = axiosInstance as unknown as ApiInstance

export default api
