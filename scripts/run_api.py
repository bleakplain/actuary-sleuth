#!/usr/bin/env python3
"""启动 RAG 法规知识平台 API 服务。"""

import sys
import os
import uvicorn

if __name__ == "__main__":
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
