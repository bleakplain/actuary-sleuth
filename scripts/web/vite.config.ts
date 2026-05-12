import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'child_process'
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
    console.warn('[vite] .run file not found; API proxy will not work. Start backend first.')
  }
  return 0
}

function getFrontendPort(): number {
  // master 分支前端固定 8000，其他（worktree/detached HEAD）随机
  try {
    const branch = execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf-8' }).trim()
    return branch === 'master' ? 8000 : 0
  } catch {
    return 0
  }
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: getFrontendPort(),
    proxy: {
      '/api': {
        target: `http://localhost:${getApiPort()}`,
        changeOrigin: true,
      },
    },
  },
})
