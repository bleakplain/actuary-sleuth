#!/usr/bin/env bash
cd "$(dirname "$0")"

# 若端口 3000 已占用，先停服
# WSL 下 lsof 可能无法识别 Windows 侧进程，优先用 fuser
port=3000
killed=false

if command -v fuser &>/dev/null; then
  pids=$(fuser "$port/tcp" 2>/dev/null)
  if [ -n "$pids" ]; then
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null && echo "已停止占用端口 $port 的进程 (PID $pid)"
    done
    killed=true
  fi
elif command -v lsof &>/dev/null; then
  pids=$(lsof -ti :"$port" 2>/dev/null)
  if [ -n "$pids" ]; then
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null && echo "已停止占用端口 $port 的进程 (PID $pid)"
    done
    killed=true
  fi
fi

if [ "$killed" = true ]; then
  sleep 0.5
fi

exec node node_modules/vite/bin/vite.js "$@"
