#!/usr/bin/env bash
cd "$(dirname "$0")"

SCRIPTS_DIR="$(pwd)"
RUN_FILE="$SCRIPTS_DIR/../.run"

# 通过 .run 文件精确停止旧前端服务（仅限同一 worktree）
if [ -f "$RUN_FILE" ]; then
  old_frontend_pid=$(sed -n '3p' "$RUN_FILE" 2>/dev/null)
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

# 追加 frontend_pid 到 .run（第3行）
if [ -f "$RUN_FILE" ]; then
  echo "$VITE_PID" >> "$RUN_FILE"
else
  echo "0\n8000\n$VITE_PID" > "$RUN_FILE"
fi

wait "$VITE_PID"

# 退出时清理 frontend_pid 行
if [ -f "$RUN_FILE" ]; then
  sed -i '3d' "$RUN_FILE"
fi
