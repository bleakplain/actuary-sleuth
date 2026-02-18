#!/bin/bash
# 测试运行脚本

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "================================"
echo "Actuary Sleuth 测试套件"
echo "================================"

# 检查测试依赖
echo "📦 检查测试依赖..."
python3 -c "import pytest" 2>/dev/null || {
    echo "❌ pytest 未安装，正在安装..."
    pip install pytest pytest-cov pytest-mock coverage --break-system-packages -q
}

echo ""
echo "🧪 运行测试..."
echo "================================"

# 运行测试
if [ "$1" = "unit" ]; then
    echo "🔬 运行单元测试..."
    python3 -m pytest tests/unit/ -v --tb=short "$@"
elif [ "$1" = "integration" ]; then
    echo "🔗 运行集成测试..."
    python3 -m pytest tests/integration/ -v --tb=short "$@"
elif [ "$1" = "coverage" ]; then
    echo "📊 运行测试并生成覆盖率报告..."
    python3 -m pytest tests/ -v --cov=scripts --cov-report=html --cov-report=term "$@"
    echo ""
    echo "📊 HTML覆盖率报告: htmlcov/index.html"
else
    echo "🚀 运行所有测试..."
    python3 -m pytest tests/ -v --tb=short "$@"
fi

echo ""
echo "================================"
echo "✅ 测试完成"
echo "================================"