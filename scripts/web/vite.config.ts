import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

function readRunPort(key: string): number {
  const runFile = path.resolve(__dirname, '../.run')
  try {
    const content = fs.readFileSync(runFile, 'utf-8')
    const match = content.match(new RegExp(`^${key}=(\\d+)`, 'm'))
    if (match) return parseInt(match[1], 10)
  } catch {}
  return 0
}

function getApiPort(): number {
  const port = readRunPort('backend_port')
  if (!port) console.warn('[vite] backend_port not found in .run; API proxy will not work.')
  return port
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: readRunPort('frontend_port'),
    proxy: {
      '/api': {
        target: `http://localhost:${getApiPort()}`,
        changeOrigin: true,
      },
    },
  },
})
