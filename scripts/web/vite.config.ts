import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

function getApiPort(): number {
  const runFile = path.resolve(__dirname, '../.run')
  const content = fs.readFileSync(runFile, 'utf-8')
  const match = content.match(/^backend_port=(\d+)/m)
  if (!match) {
    console.error('Error: backend_port not found in .run file. Start backend first.')
    process.exit(1)
  }
  return parseInt(match[1], 10)
}

export default defineConfig({
  plugins: [react()],
  cacheDir: '/tmp/vite_cache',
  server: {
    host: '0.0.0.0',
    port: 8000,
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://localhost:${getApiPort()}`,
        changeOrigin: true,
      },
    },
  },
})
