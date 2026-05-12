#!/usr/bin/env python3
"""统一启动/重启脚本。

用法:
    python deploy.py               # 启动后端 + 前端（默认 all）
    python deploy.py all           # 启动后端 + 前端
    python deploy.py backend       # 仅后端
    python deploy.py frontend      # 仅前端
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.resolve()
RUN_FILE = SCRIPTS_DIR / ".run"
WEB_DIR = SCRIPTS_DIR / "web"
VITE_BIN = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"


def _read_run() -> dict[str, str]:
    try:
        data = {}
        for line in RUN_FILE.read_text().strip().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
        return data
    except FileNotFoundError:
        return {}


def _write_run_batch(updates: dict[str, str]) -> None:
    data = _read_run()
    data.update(updates)
    data.pop("PORT", None)  # legacy key cleanup
    RUN_FILE.write_text("".join(f"{k}={v}\n" for k, v in data.items()))


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _stop_old_service(role: str) -> None:
    """停止指定角色的旧服务进程。"""
    data = _read_run()
    pid_str = data.get(f"{role}_pid")
    if not pid_str:
        return
    try:
        pid = int(pid_str)
    except ValueError:
        return
    if not _is_alive(pid):
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not _is_alive(pid):
            break
        time.sleep(0.1)
    if _is_alive(pid):
        os.kill(pid, signal.SIGKILL)
    print(f"已停止旧{role}服务 (PID {pid})")


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


def _load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv(SCRIPTS_DIR / ".env")


def _start_backend(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["UVICORN_LOOP"] = "asyncio"
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.app:app",
         "--host", "0.0.0.0", "--port", str(port),
         *(["--reload"] if env.get("DEBUG", "").lower() == "true" else [])],
        cwd=str(SCRIPTS_DIR),
        env=env,
    )


def _start_frontend() -> subprocess.Popen:
    if not VITE_BIN.exists():
        print(f"错误: Vite 未安装，请先在 {WEB_DIR} 运行 npm install", file=sys.stderr)
        sys.exit(1)
    return subprocess.Popen(
        ["node", str(VITE_BIN)],
        cwd=str(WEB_DIR),
    )


def _cleanup(*procs: subprocess.Popen) -> None:
    for p in procs:
        try:
            p.terminate()
        except (ProcessLookupError, OSError):
            pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        except (ProcessLookupError, OSError):
            pass


def _supervise(procs: list[subprocess.Popen]) -> None:
    shutting_down = False

    def _stop(signum: int = 0, frame: object = None) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        print("\n正在停止服务...")
        _cleanup(*procs)
        os._exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        if len(procs) == 1:
            procs[0].wait()
        else:
            while all(p.poll() is None for p in procs):
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _stop()


def _run_backend() -> None:
    _load_env()
    _stop_old_service("backend")
    actual_port = _find_available_port(0)
    proc = _start_backend(actual_port)
    _write_run_batch({
        "backend_pid": str(proc.pid),
        "backend_port": str(actual_port),
    })
    print(f"后端运行于 http://localhost:{actual_port} (PID {proc.pid})")
    _supervise([proc])


def _resolve_frontend_port() -> int:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(SCRIPTS_DIR),
        )
        if result.stdout.strip() == "master":
            return 8000
    except Exception:
        pass
    return _find_available_port(0)


def _run_frontend() -> None:
    _load_env()
    _stop_old_service("frontend")
    data = _read_run()
    if "backend_port" not in data:
        print("警告: 未检测到后端端口，API 代理将不可用。请确保后端已启动。")
    frontend_port = _resolve_frontend_port()
    _write_run_batch({"frontend_port": str(frontend_port)})
    proc = _start_frontend()
    _write_run_batch({"frontend_pid": str(proc.pid)})
    print(f"前端运行于 http://localhost:{frontend_port} (PID {proc.pid})")
    _supervise([proc])


def _run_all() -> None:
    _load_env()
    _stop_old_service("backend")
    _stop_old_service("frontend")
    backend_port = _find_available_port(0)
    frontend_port = _resolve_frontend_port()
    backend_proc = _start_backend(backend_port)
    # Write ports BEFORE starting frontend so Vite can read them
    _write_run_batch({
        "backend_pid": str(backend_proc.pid),
        "backend_port": str(backend_port),
        "frontend_port": str(frontend_port),
    })
    frontend_proc = _start_frontend()
    _write_run_batch({"frontend_pid": str(frontend_proc.pid)})
    print(f"后端运行于 http://localhost:{backend_port} (PID {backend_proc.pid})")
    print(f"前端运行于 http://localhost:{frontend_port} (PID {frontend_proc.pid})")
    _supervise([backend_proc, frontend_proc])


def main() -> None:
    parser = argparse.ArgumentParser(description="Actuary Sleuth 开发服务启动器")
    parser.add_argument(
        "mode", nargs="?", default="all",
        choices=["all", "backend", "frontend"],
        help="启动模式: all=后端+前端, backend=仅后端, frontend=仅前端",
    )
    args = parser.parse_args()

    scripts_str = str(SCRIPTS_DIR)
    if scripts_str not in sys.path:
        sys.path.insert(0, scripts_str)

    if args.mode == "all":
        _run_all()
    elif args.mode == "backend":
        _run_backend()
    else:
        _run_frontend()


if __name__ == "__main__":
    main()
