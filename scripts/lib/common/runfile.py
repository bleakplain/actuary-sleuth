"""读取 deploy.py 生成的 .run 文件，获取运行时端口和 PID。"""
from pathlib import Path

_RUN_FILE = Path(__file__).resolve().parent.parent.parent / ".run"


def read_run_config() -> dict[str, str]:
    """读取 .run 文件内容为 key=value 字典。"""
    try:
        data = {}
        for line in _RUN_FILE.read_text().strip().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()
        return data
    except FileNotFoundError:
        return {}


def get_backend_port() -> int:
    """获取当前后端服务端口号，未找到时返回 8000。"""
    return int(read_run_config().get("backend_port", "8000"))


def get_backend_base_url() -> str:
    """获取后端服务的完整 base URL，如 http://localhost:49384。"""
    return f"http://localhost:{get_backend_port()}"
