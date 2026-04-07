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

    import shutil
    import subprocess

    # 若端口 8000 已占用，先停服
    # WSL 下 lsof 可能无法识别 Windows 侧进程，优先用 fuser
    def stop_service(port: int):
        killed = False
        if shutil.which("fuser"):
            try:
                result = subprocess.run(
                    ["fuser", f"{port}/tcp"], capture_output=True, text=True,
                )
                pids = result.stdout.strip().split() if result.stdout.strip() else []
                for pid in pids:
                    pid = pid.strip()
                    if pid:
                        os.kill(int(pid), 9)
                        print(f"已停止占用端口 {port} 的进程 (PID {pid})")
                        killed = True
            except (ProcessLookupError, PermissionError, ValueError):
                pass
        else:
            try:
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"], capture_output=True, text=True,
                )
                pids = result.stdout.strip().split("\n") if result.stdout.strip() else []
                for pid in pids:
                    pid = pid.strip()
                    if pid:
                        os.kill(int(pid), 9)
                        print(f"已停止占用端口 {port} 的进程 (PID {pid})")
                        killed = True
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        return killed

    api_port = 8000
    if stop_service(api_port):
        for _ in range(10):
            check_cmd = (["fuser", f"{api_port}/tcp"] if shutil.which("fuser")
                         else ["lsof", "-ti", f":{api_port}"])
            if not subprocess.run(check_cmd, capture_output=True, text=True).stdout.strip():
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
