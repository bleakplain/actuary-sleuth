#!/usr/bin/env python3
"""启动 RAG 法规知识平台 API 服务。"""

import argparse
import os
import socket
import sys
import time
from pathlib import Path

RUN_FILE = Path(__file__).parent / ".run"


def _read_run_file() -> dict[str, str]:
    """读取 .run 文件，返回 key=value 字典。"""
    try:
        data = {}
        for line in RUN_FILE.read_text().strip().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
        return data
    except FileNotFoundError:
        return {}


def _get_process_cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _stop_old_service(scripts_dir: str) -> int:
    """通过 .run 文件中的 backend_pid 精确停止旧服务（仅限同一 worktree）。
    返回旧端口号（可用于端口复用），无记录时返回 0。"""
    data = _read_run_file()
    old_port = int(data.get("backend_port", 0) or 0)
    old_pid = data.get("backend_pid")
    if not old_pid:
        return old_port
    try:
        pid = int(old_pid)
    except ValueError:
        return 0
    cwd = _get_process_cwd(pid)
    if cwd is not None and not cwd.startswith(scripts_dir):
        return 0
    try:
        os.kill(pid, 9)
        print(f"已停止旧后端服务 (PID {pid})")
        for _ in range(10):
            if _get_process_cwd(pid) is None:
                break
            time.sleep(0.2)
    except ProcessLookupError:
        pass
    return old_port


def _find_available_port(preferred: int = 0) -> int:
    if preferred > 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def _write_run_file(backend_pid: int, backend_port: int) -> None:
    RUN_FILE.write_text(f"backend_pid={backend_pid}\nbackend_port={backend_port}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="启动 API 服务")
    parser.add_argument("--port", type=int, default=0, help="端口号（0=自动分配）")
    args = parser.parse_args()

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    env_file = Path(scripts_dir) / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

    preferred_port = _stop_old_service(scripts_dir) or args.port

    actual_port = _find_available_port(preferred_port)

    import uvicorn
    from uvicorn.config import Config
    from uvicorn.server import Server

    # RAGAS 不兼容 uvloop，强制使用标准 asyncio 事件循环
    os.environ.setdefault("UVICORN_LOOP", "asyncio")

    config = Config(
        "api.app:app",
        host="0.0.0.0",
        port=actual_port,
        reload=os.environ.get("DEBUG", "false").lower() == "true",
        log_level="info",
        loop="asyncio",
    )
    server = Server(config=config)

    _write_run_file(os.getpid(), actual_port)
    print(f"API running on http://localhost:{actual_port}")

    server.run()

    try:
        RUN_FILE.unlink()
    except FileNotFoundError:
        pass
