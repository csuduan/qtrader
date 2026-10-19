import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  build: {
    rollupOptions: {
      output: {
        // 只分包echarts（含其依赖zrender）；vue/element-plus不手动分包——
        // vue的运行时内核在@vue/*子包，按包名拆分会造成vue chunk反向依赖entry chunk，
        // 模块求值顺序错乱引发"Cannot access 'RefImpl' before initialization"白屏
        manualChunks: {
          echarts: ['echarts', 'zrender']
        }
      }
    }
  },
  server: {
    port: 3000,
    host: "0.0.0.0",
    allowedHosts: ['dev.tsing.cc'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'http://localhost:8000',
        ws: true,
        changeOrigin: true
      }
    }
  }
})
