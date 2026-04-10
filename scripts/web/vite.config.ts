import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

function getApiPort(): number {
  try {
    const runFile = path.resolve(__dirname, '../.run')
    const content = fs.readFileSync(runFile, 'utf-8').trim().split('\n')
    return parseInt(content[1], 10)
  } catch {
    return 8000
  }
}

export default defineConfig({
  plugins: [react()],
  cacheDir: '/tmp/vite_cache',
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://localhost:${getApiPort()}`,
        changeOrigin: true,
      },
    },
  },
})
