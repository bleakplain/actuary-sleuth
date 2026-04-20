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

function getFrontendPort(): number {
  // 主仓库前端固定 8000，worktree 随机
  const gitPath = path.resolve(__dirname, '../../.git')
  try {
    const stat = fs.statSync(gitPath)
    // worktree 的 .git 是文件，主仓库是目录
    if (stat.isFile()) {
      return 0  // worktree: 随机端口
    }
  } catch {
    // .git 不存在，使用随机端口
    return 0
  }
  return 8000  // 主仓库: 固定 8000
}

export default defineConfig({
  plugins: [react()],
  cacheDir: '/tmp/vite_cache',
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
