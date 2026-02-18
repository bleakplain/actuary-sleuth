# 单元测试指南

## 概述

Actuary Sleuth 项目使用 pytest 作为测试框架，提供单元测试和集成测试。

## 测试结构

```
tests/
├── conftest.py           # pytest 配置和 fixtures
├── pytest.ini            # pytest 配置文件
├── unit/                 # 单元测试
│   ├── test_id_generator.py
│   └── test_exceptions.py
├── integration/          # 集成测试
│   └── test_audit_workflow.py
└── run_tests.sh          # 测试运行脚本
```

## 运行测试

### 运行所有测试
```bash
cd /root/.openclaw/workspace/skills/actuary-sleuth
./tests/run_tests.sh
```

### 运行单元测试
```bash
./tests/run_tests.sh unit
python3 -m pytest tests/unit/ -v
```

### 运行集成测试
```bash
./tests/run_tests.sh integration
python3 -m pytest tests/integration/ -v
```

### 生成覆盖率报告
```bash
./tests/run_tests.sh coverage
python3 -m pytest tests/ --cov=scripts --cov-report=html
```

## 测试覆盖

当前测试覆盖:
- ✅ ID生成器 (91% 覆盖)
- ✅ 异常处理 (99% 覆盖)
- ✅ 审核工作流程 (集成测试)

## 编写测试

### 单元测试模板

```python
import pytest
from infrastructure.module import FunctionToTest

class TestFunctionToTest:
    """功能测试类"""

    def test_basic_functionality(self):
        """测试基本功能"""
        result = FunctionToTest()
        assert result is not None

    @pytest.fixture
    def sample_data(self):
        """示例数据"""
        return {"key": "value"}

    def test_with_fixture(self, sample_data):
        """使用 fixture 的测试"""
        result = FunctionToTest(sample_data)
        assert result.key == "value"
```

### 集成测试模板

```python
import pytest
from pathlib import Path

@pytest.mark.integration
def test_workflow():
    """测试完整工作流程"""
    # 设置
    input_file = Path("test_input.json")

    # 执行
    result = run_process(input_file)

    # 验证
    assert result.success == True
```

## 标记说明

- `@pytest.mark.unit`: 单元测试
- `@pytest.mark.integration`: 集成测试
- `@pytest.mark.slow`: 慢速测试

## 最佳实践

1. **命名规范**: 测试文件以 `test_` 开头，测试类以 `Test` 开头
2. **独立性**: 每个测试应该独立运行
3. **清晰性**: 测试名称应该清晰描述测试内容
4. **fixtures**: 使用 fixtures 复用测试数据
5. **覆盖率**: 目标是 80% 以上的代码覆盖率

## 持续集成

测试可以集成到 CI/CD 流程中：
```yaml
test:
  script:
    - python3 -m pytest tests/ --cov=scripts --cov-report=xml
  coverage: '/Total:\s+(\d+%)/'
```
