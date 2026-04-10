#!/usr/bin/env python3
"""启动 RAG 法规知识平台 API 服务。"""

import argparse
import os
import socket
import sys
import time
from pathlib import Path

RUN_FILE = Path(__file__).parent / ".run"


def _read_run_file() -> tuple[int | None, int | None]:
    """读取 .run 文件，返回 (backend_pid, backend_port)。"""
    try:
        lines = RUN_FILE.read_text().strip().splitlines()
        return int(lines[0]), int(lines[1])
    except (FileNotFoundError, ValueError, IndexError):
        return None, None


def _get_process_cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _stop_old_service(scripts_dir: str) -> None:
    """通过 .run 文件中的 PID 精确停止旧服务（仅限同一 worktree）。"""
    old_pid, _ = _read_run_file()
    if old_pid is None:
        return
    cwd = _get_process_cwd(old_pid)
    if cwd is None or not cwd.startswith(scripts_dir):
        return
    try:
        os.kill(old_pid, 9)
        print(f"已停止旧后端服务 (PID {old_pid})")
        for _ in range(10):
            if _get_process_cwd(old_pid) is None:
                break
            time.sleep(0.2)
    except ProcessLookupError:
        pass
    finally:
        try:
            RUN_FILE.unlink()
        except FileNotFoundError:
            pass


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
    """写入 .run 文件，格式：backend_pid\nbackend_port\nfrontend_pid"""
    RUN_FILE.write_text(f"{backend_pid}\n{backend_port}\n")


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

    _stop_old_service(scripts_dir)

    actual_port = _find_available_port(args.port)

    import uvicorn
    from uvicorn.config import Config
    from uvicorn.server import Server

    config = Config(
        "api.app:app",
        host="0.0.0.0",
        port=actual_port,
        reload=os.environ.get("DEBUG", "false").lower() == "true",
        log_level="info",
    )
    server = Server(config=config)

    _write_run_file(os.getpid(), actual_port)
    print(f"API running on http://localhost:{actual_port}")

    server.run()

    try:
        RUN_FILE.unlink()
    except FileNotFoundError:
        pass
