import { defineConfig, mergeConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createShizuhaConfig } from '@shizuha/ui/vite'

const basePath = process.env.VITE_BASE_PATH || '/'
const serviceName = 'admin'

export default defineConfig(async () => {
  return mergeConfig(
    createShizuhaConfig({ port: 80, serviceName }),
    defineConfig({
      plugins: [react()],
      server: {
        proxy: basePath === '/' ? {
          '/api': {
            target: process.env.VITE_API_URL || 'http://localhost:8003',
            changeOrigin: true,
          },
        } : {},
      },
    })
  )
})
