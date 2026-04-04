#!/usr/bin/env python3
"""启动 RAG 法规知识平台 API 服务。"""

import sys
import os
import time
from pathlib import Path

if __name__ == "__main__":
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # 加载 .env 文件
    env_file = Path(scripts_dir) / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

    import subprocess

    # 若端口 8000 已占用，先停服
    def stop_service(port: int):
        try:
            result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
            pids = result.stdout.strip().split("\n") if result.stdout.strip() else []
            for pid in pids:
                pid = pid.strip()
                if pid:
                    os.kill(int(pid), 9)
                    print(f"已停止占用端口 {port} 的进程 (PID {pid})")
            return len(pids) > 0
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            return False

    if stop_service(8000):
        for _ in range(10):
            if not subprocess.run(["lsof", "-ti", ":8000"], capture_output=True, text=True).stdout.strip():
                break
            time.sleep(0.5)

    import uvicorn

    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=os.environ.get("DEBUG", "false").lower() == "true",
        log_level="info",
    )
