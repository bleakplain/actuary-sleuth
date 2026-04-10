#!/usr/bin/env bash
cd "$(dirname "$0")"

SCRIPTS_DIR="$(pwd)"
RUN_FILE="$SCRIPTS_DIR/../.run"

_run_get() {
  grep "^$1=" "$RUN_FILE" 2>/dev/null | head -1 | cut -d= -f2
}

# 通过 .run 文件精确停止旧前端服务（仅限同一 worktree）
if [ -f "$RUN_FILE" ]; then
  old_frontend_pid=$(_run_get frontend_pid)
  if [ -n "$old_frontend_pid" ] && [ -d "/proc/$old_frontend_pid" ]; then
    old_cwd=$(readlink "/proc/$old_frontend_pid/cwd" 2>/dev/null)
    case "$old_cwd" in
      "$SCRIPTS_DIR"*)
        kill -9 "$old_frontend_pid" 2>/dev/null && echo "已停止旧前端服务 (PID $old_frontend_pid)"
        sleep 0.2
        ;;
    esac
  fi
fi

# 启动 Vite 并将 frontend_pid 追加到 .run
node node_modules/vite/bin/vite.js "$@" &
VITE_PID=$!

if [ -f "$RUN_FILE" ]; then
  sed -i "/^frontend_pid=/d" "$RUN_FILE"
  echo "frontend_pid=$VITE_PID" >> "$RUN_FILE"
else
  echo "Error: .run file not found. Start backend first." >&2
  exit 1
fi

wait "$VITE_PID"

# 退出时清理 frontend_pid
if [ -f "$RUN_FILE" ]; then
  sed -i "/^frontend_pid=/d" "$RUN_FILE"
fi
