import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

function getApiPort(): number {
  const runFile = path.resolve(__dirname, '../.run')
  try {
    const content = fs.readFileSync(runFile, 'utf-8')
    const match = content.match(/^backend_port=(\d+)/m)
    if (match) {
      return parseInt(match[1], 10)
    }
  } catch {
    // .run file not found, use default
  }
  return 8000
}

export default defineConfig({
  plugins: [react()],
  cacheDir: '/tmp/vite_cache',
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: `http://localhost:${getApiPort()}`,
        changeOrigin: true,
      },
    },
  },
})
