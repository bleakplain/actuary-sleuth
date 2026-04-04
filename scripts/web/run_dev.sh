#!/usr/bin/env bash
cd "$(dirname "$0")"

# 若端口 3000 已占用，先停服
if command -v lsof &>/dev/null; then
  pids=$(lsof -ti :3000 2>/dev/null)
  if [ -n "$pids" ]; then
    for pid in $pids; do
      kill -9 "$pid" 2>/dev/null
      echo "已停止占用端口 3000 的进程 (PID $pid)"
    done
  fi
fi

exec node node_modules/vite/bin/vite.js "$@"
