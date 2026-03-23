# Actuary Sleuth - 综合改进方案

生成时间: 2026-03-23
源文档: research.md

本方案基于 research.md 的分析内容生成，包含以下章节：

---

## 一、问题修复方案

### 🔴 安全问题 (P0/P1 - 必须修复)

#### 问题 1.1: API密钥硬编码泄露

##### 问题概述
- **文件**: `scripts/config/settings.json:23`
- **严重程度**: 🔴 Critical (P0)
- **影响范围**: 密钥泄露可能导致未授权访问、API费用被恶意消耗、飞书群组被未授权操作

##### 当前代码
```json
// scripts/config/settings.json:23
{
  "llm": {
    "provider": "zhipu",
    "api_key": "7d0a2b4545c94ca088f4d869a9e2cbbd.oRxlgkhqRF1rbjNp"
  },
  "feishu": {
    "app_id": "cli_a900c2ed51335ccd",
    "app_secret": "xU3udM9Wax1HFwCXFdwwdgXPH0xjb1TT"
  }
}
```

##### 修复方案
**问题分析**:
当前配置文件中明文存储了智谱AI API密钥和飞书应用密钥。虽然项目已有 `ConfigValidator` 模块，但配置加载逻辑未强制使用环境变量。

**解决思路**:
1. 从配置文件中移除所有敏感信息
2. 修改配置加载逻辑，强制从环境变量读取密钥
3. 添加配置验证，拒绝从配置文件读取密钥
4. 提供环境变量配置示例文件

**实施步骤**:
1. 修改 `scripts/lib/config.py` 中的 LLM 和飞书配置加载逻辑
2. 更新 `scripts/config/settings.json`，移除敏感字段
3. 创建 `.env.example` 文件作为环境变量模板
4. 更新文档说明环境变量配置方式

##### 代码变更

**步骤1: 修改配置加载逻辑**

```python
# scripts/lib/config.py
# 在现有的 LLM 配置加载部分添加验证

class Config:
    # ... 现有代码 ...

    def _load_llm_config(self, config_dict: Dict[str, Any]) -> LLMConfig:
        """加载 LLM 配置，强制从环境变量读取 API 密钥"""
        from lib.common.config_validator import ConfigValidator

        provider = config_dict.get('provider', 'ollama')
        model = config_dict.get('model', '')
        base_url = config_dict.get('base_url', '')
        timeout = config_dict.get('timeout', 60)

        # 如果配置文件中包含 api_key，拒绝使用并警告
        if 'api_key' in config_dict:
            import warnings
            warnings.warn(
                "配置文件中检测到 api_key。出于安全考虑，API密钥必须通过环境变量设置。"
                "请使用环境变量 ZHIPU_API_KEY（智谱）或 OPENAI_API_KEY（OpenAI）。",
                stacklevel=2
            )
            # 不使用配置文件中的密钥

        # 根据提供商从环境变量获取 API 密钥
        api_key = None
        if provider == 'zhipu':
            api_key = ConfigValidator.validate_zhipu_api_key()  # 强制从环境变量读取
        elif provider == 'openai':
            api_key = ConfigValidator.require_api_key('OPENAI_API_KEY', 'OpenAI')

        base_url = ConfigValidator.validate_base_url(base_url, provider)
        timeout = ConfigValidator.validate_timeout(timeout, provider)
        model = ConfigValidator.validate_model_name(model, provider)

        return LLMConfig(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout
        )

    def _load_feishu_config(self, config_dict: Dict[str, Any]) -> FeishuConfig:
        """加载飞书配置，强制从环境变量读取密钥"""
        from lib.common.config_validator import ConfigValidator

        # 如果配置文件中包含敏感信息，拒绝使用
        if 'app_secret' in config_dict:
            import warnings
            warnings.warn(
                "配置文件中检测到 app_secret。出于安全考虑，飞书应用密钥必须通过环境变量设置。",
                stacklevel=2
            )

        app_id = config_dict.get('app_id')
        target_group_id = config_dict.get('target_group_id', '')

        # 强制从环境变量读取密钥
        app_id, app_secret = ConfigValidator.validate_feishu_app_config(
            app_id=app_id,
            app_secret=None  # 强制从环境变量读取
        )

        return FeishuConfig(
            app_id=app_id,
            app_secret=app_secret,
            target_group_id=target_group_id
        )
```

**步骤2: 更新配置文件**

```json
// scripts/config/settings.json
{
  "llm": {
    "provider": "zhipu",
    "model": "glm-4-flash",
    "base_url": "https://open.bigmodel.cn/api/paas/v4/",
    "timeout": 120
    // api_key 已移除，请使用环境变量 ZHIPU_API_KEY
  },
  "feishu": {
    "app_id": "",
    "target_group_id": "oc_xxxxxxxxxxxxx"
    // app_secret 已移除，请使用环境变量 FEISHU_APP_SECRET
  }
}
```

**步骤3: 创建环境变量示例文件**

```bash
# .env.example
# 复制此文件为 .env 并填入实际的密钥

# 智谱 AI API 密钥（必需）
ZHIPU_API_KEY=your_zhipu_api_key_here

# 飞书应用配置（必需）
FEISHU_APP_ID=cli_your_app_id_here
FEISHU_APP_SECRET=your_app_secret_here

# OpenAI API 密钥（可选，如使用 OpenAI）
# OPENAI_API_KEY=your_openai_api_key_here
```

**步骤4: 更新 .gitignore**

```
# .gitignore
.env
.env.local
.env.*.local
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/config.py` | 修改 | 添加配置验证逻辑 |
| `scripts/config/settings.json` | 修改 | 移除敏感字段 |
| `.env.example` | 新增 | 环境变量模板 |
| `.gitignore` | 修改 | 忽略 .env 文件 |
| `README.md` | 修改 | 添加环境变量配置说明 |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 环境变量 | 安全、标准做法、易于部署 | 需要文档说明 | ✅ |
| 加密配置文件 | 可提交到仓库 | 需要密钥管理、复杂度高 | ⏳ |
| 密钥管理服务 | 最安全、易于轮换 | 依赖外部服务、成本高 | ⏳ |

##### 注意事项
1. **向后兼容**: 现有部署需要配置环境变量
2. **开发体验**: 本地开发需要设置环境变量
3. **CI/CD**: 需要在 CI/CD 平台配置环境变量
4. **密钥轮换**: 建议定期轮换 API 密钥

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 现有部署中断 | 中 | 高 | 提前通知、提供迁移指南 |
| 开发者忘记配置 | 高 | 中 | 提供清晰的错误提示 |
| 密钥泄露（日志） | 低 | 高 | 确保密钥不被记录到日志 |

##### 测试建议

```python
# scripts/tests/lib/config/test_security.py
import os
import pytest
from lib.common.config_validator import ConfigValidator, ConfigurationError
from lib.config import Config

class TestAPIKeySecurity:
    """测试 API 密钥安全"""

    def test_config_rejects_file_api_key(self, tmp_path):
        """测试配置文件中的 API 密钥被拒绝"""
        import warnings

        config_file = tmp_path / "settings.json"
        config_file.write_text('{"llm": {"api_key": "secret123"}}')

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = Config(str(config_file))
            assert len(w) > 0
            assert "api_key" in str(w[0].message).lower()
            assert config.llm.api_key != "secret123"

    def test_requires_zhipu_api_key_from_env(self, monkeypatch):
        """测试必须从环境变量读取智谱 API 密钥"""
        monkeypatch.delenv('ZHIPU_API_KEY', raising=False)

        with pytest.raises(ConfigurationError, match="未设置"):
            ConfigValidator.validate_zhipu_api_key()

    def test_validates_zhipu_api_key_format(self, monkeypatch):
        """测试验证智谱 API 密钥格式"""
        monkeypatch.setenv('ZHIPU_API_KEY', 'invalid-format')

        with pytest.raises(ConfigurationError, match="格式无效"):
            ConfigValidator.validate_zhipu_api_key()

    def test_feishu_config_from_env(self, monkeypatch):
        """测试飞书配置从环境变量读取"""
        monkeypatch.setenv('FEISHU_APP_ID', 'test_app_id')
        monkeypatch.setenv('FEISHU_APP_SECRET', 'test_secret')

        app_id, app_secret = ConfigValidator.validate_feishu_app_config()
        assert app_id == 'test_app_id'
        assert app_secret == 'test_secret'
```

##### 验收标准
- [ ] 配置文件中不包含任何明文 API 密钥
- [ ] 尝试从配置文件读取密钥时产生警告并拒绝使用
- [ ] 未设置环境变量时提供清晰的错误提示
- [ ] 所有测试通过
- [ ] 文档更新完成

---

#### 问题 1.2: subprocess命令注入风险修复

##### 问题概述
- **文件**: `scripts/lib/preprocessing/document_fetcher.py:84`
- **严重程度**: 🔴 High (P0)
- **影响范围**: 虽然当前有验证，但未显式声明 `shell=False`，存在潜在命令注入风险

##### 当前代码
```python
# scripts/lib/preprocessing/document_fetcher.py:84
result = subprocess.run(
    ['feishu2md', 'download', safe_url],
    capture_output=True,
    text=True,
    timeout=timeout,
    check=False
)
```

##### 修复方案
**问题分析**:
当前代码虽然经过 URL 验证，但 `subprocess.run` 默认 `shell=False` 未显式声明。虽然列表形式调用天然安全，但显式声明可以提高代码可读性并防止未来误改。

**解决思路**:
1. 显式声明 `shell=False`
2. 添加参数白名单验证
3. 添加安全检查函数
4. 增强错误处理

**实施步骤**:
1. 修改 `subprocess.run` 调用，添加 `shell=False`
2. 创建参数验证函数
3. 更新错误处理

##### 代码变更

```python
# scripts/lib/preprocessing/document_fetcher.py
import os
import re
import subprocess
from contextlib import typing Generator
from lib.common.exceptions import DocumentFetchError


# 安全常量
SAFE_URL_TEMPLATE = 'https://feishu.cn/docx/{token}'
FEISHU2MD_CMD = 'feishu2md'
MAX_SAFE_TIMEOUT = 300  # 最大安全超时时间


def _validate_command_args(url: str, timeout: int) -> None:
    """验证命令参数安全性"""
    # 验证 URL 格式（再次检查）
    if not url.startswith('https://'):
        raise DocumentFetchError(f"URL 必须使用 HTTPS: {url}")

    # 验证超时值范围
    if not isinstance(timeout, int) or timeout <= 0:
        raise DocumentFetchError(f"无效的超时值: {timeout}")

    if timeout > MAX_SAFE_TIMEOUT:
        raise DocumentFetchError(f"超时值过大（最大 {MAX_SAFE_TIMEOUT} 秒）: {timeout}")

    # 检查 URL 中不包含危险字符
    dangerous_chars = [';', '&', '|', '$', '`', '\n', '\r']
    if any(char in url for char in dangerous_chars):
        raise DocumentFetchError(f"URL 包含危险字符")


def fetch_feishu_document(
    document_url: str,
    output_dir: str = "/tmp",
    timeout: int = 30
) -> str:
    """获取飞书文档内容（安全版本）"""
    doc_token = _validate_feishu_url(document_url)
    safe_url = SAFE_URL_TEMPLATE.format(token=doc_token)

    # 验证命令参数
    _validate_command_args(safe_url, timeout)

    md_filename = f"{doc_token}.md"

    try:
        os.makedirs(output_dir, exist_ok=True)

        with _change_directory(output_dir):
            # 显式使用 shell=False 防止命令注入
            result = subprocess.run(
                [FEISHU2MD_CMD, 'download', safe_url],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False  # 显式声明，确保安全
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "未知错误"
                raise subprocess.CalledProcessError(
                    result.returncode,
                    [FEISHU2MD_CMD, 'download', safe_url],
                    result.stderr,
                    result.stdout
                )

            md_file_path = os.path.join(output_dir, md_filename)

            try:
                file_size = os.path.getsize(md_file_path)
            except OSError:
                raise DocumentFetchError(f"未生成 Markdown 文件: {md_file_path}")

            if file_size == 0:
                raise DocumentFetchError(f"生成的文件为空: {md_file_path}")

            if file_size > 10 * 1024 * 1024:
                raise DocumentFetchError(f"文件过大: {file_size} bytes")

            with open(md_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if not content.strip():
                raise DocumentFetchError(f"文件内容为空: {md_file_path}")

            # 清理临时文件
            try:
                os.remove(md_file_path)
            except OSError:
                pass  # 清理失败不影响主流程

            return content

    except subprocess.CalledProcessError as e:
        error_msg = f"feishu2md 下载失败 (退出码: {e.returncode})"
        if e.stderr:
            error_msg += f"\n错误输出: {e.stderr[:500]}"  # 限制错误长度
        raise DocumentFetchError(error_msg) from e

    except subprocess.TimeoutExpired:
        raise DocumentFetchError(f"下载超时 ({timeout}秒)")

    except FileNotFoundError:
        raise DocumentFetchError("feishu2md 未安装。请安装: gem install feishu2md")

    except PermissionError as e:
        raise DocumentFetchError(f"权限错误: {e}")

    except OSError as e:
        raise DocumentFetchError(f"系统错误: {e}")
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/preprocessing/document_fetcher.py` | 修改 | 添加安全验证和 shell=False |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 列表 + shell=False | 最安全、Python推荐 | 需要验证参数 | ✅ |
| 使用 SDK | 无注入风险 | 需要重写、依赖SDK | ⏳ |
| 字符串转义 | 灵活 | 易出错、不推荐 | ❌ |

##### 注意事项
1. 保持 URL 验证的严格性
2. 临时文件清理在成功后执行
3. 错误消息限制长度防止日志注入

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| feishu2md 漏洞 | 低 | 高 | 使用固定版本、监控更新 |
| 参数验证绕过 | 极低 | 高 | 多层验证、单元测试 |
| 临时文件泄露 | 低 | 中 | 自动清理、使用私有目录 |

##### 测试建议

```python
# scripts/tests/lib/preprocessing/test_security.py
import pytest
from lib.preprocessing.document_fetcher import fetch_feishu_document, _validate_command_args
from lib.common.exceptions import DocumentFetchError

class TestCommandInjectionPrevention:
    """测试命令注入防护"""

    def test_rejects_dangerous_chars_in_url(self):
        """测试拒绝包含危险字符的 URL"""
        dangerous_urls = [
            "https://feishu.cn/docx/abc; rm -rf /",
            "https://feishu.cn/docx/abc$(cat /etc/passwd)",
            "https://feishu.cn/docx/abc`whoami`",
            "https://feishu.cn/docx/abc\nmalicious",
        ]
        for url in dangerous_urls:
            with pytest.raises(DocumentFetchError, match="危险字符"):
                _validate_command_args(url, 30)

    def test_validates_timeout_range(self):
        """测试超时值验证"""
        with pytest.raises(DocumentFetchError):
            _validate_command_args("https://feishu.cn/docx/abc123", -1)

        with pytest.raises(DocumentFetchError):
            _validate_command_args("https://feishu.cn/docx/abc123", 1000)

    def test_requires_https(self):
        """测试必须使用 HTTPS"""
        with pytest.raises(DocumentFetchError, match="HTTPS"):
            _validate_command_args("http://feishu.cn/docx/abc123", 30)

    @pytest.mark.integration
    def test_uses_shell_false(self, monkeypatch):
        """测试使用 shell=False"""
        # 记录 subprocess.run 的调用
        calls = []
        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            calls.append({'args': args, 'kwargs': kwargs})
            return original_run(*args, **kwargs)

        monkeypatch.setattr(subprocess, 'run', mock_run)
        monkeypatch.setenv('PATH', '/usr/bin:/bin')  # 确保 feishu2md 不在路径中

        try:
            fetch_feishu_document("https://test.feishu.cn/docx/test12345678")
        except:
            pass  # 预期失败

        assert len(calls) > 0
        assert calls[0]['kwargs'].get('shell') is False
```

##### 验收标准
- [ ] `subprocess.run` 调用显式声明 `shell=False`
- [ ] 参数验证函数覆盖所有危险字符
- [ ] 临时文件在成功后自动清理
- [ ] 所有安全测试通过

---

#### 问题 1.3: OpenClaw命令注入风险修复

##### 问题概述
- **文件**: `scripts/lib/reporting/export/feishu_pusher.py:169`
- **严重程度**: 🔴 High (P0)
- **影响范围**: 文件路径和消息内容未充分验证，可能被注入恶意命令

##### 当前代码
```python
# scripts/lib/reporting/export/feishu_pusher.py:169
command_args = [
    self._openclaw_bin,
    'message', 'send',
    '--channel', 'feishu',
    '--target', self._target_group_id,
    '--media', file_path,  # 未验证
    '--message', message   # 未验证
]
```

##### 修复方案
**问题分析**:
虽然已有 `validate_file_path` 验证，但消息内容和文件路径需要更严格的验证。特别是消息内容可能包含特殊字符被 shell 解析。

**解决思路**:
1. 增强文件路径验证（路径遍历防护）
2. 验证并转义消息内容
3. 显式声明 `shell=False`
4. 添加参数长度限制

**实施步骤**:
1. 扩展 `validation.py` 中的验证函数
2. 修改 `feishu_pusher.py` 中的命令构建
3. 添加消息内容清理函数

##### 代码变更

**步骤1: 增强验证模块**

```python
# scripts/lib/reporting/export/validation.py
import os
import re
from pathlib import Path
from typing import Optional
from lib.common.exceptions import InvalidParameterException, ValidationException


# 安全常量
MAX_MESSAGE_LENGTH = 500
ALLOWED_PATH_CHARS = re.compile(r'^[a-zA-Z0-9_\-./\s\:]+$')
DANGEROUS_PATH_PATTERNS = [
    r'\.\./',  # 路径遍历
    r'~/',     # 主目录
    r'/etc/',  # 系统目录
    r'/dev/',  # 设备文件
]


def validate_file_path(file_path: str, allowed_dir: Optional[str] = None) -> str:
    """
    验证文件路径（增强版）

    Args:
        file_path: 待验证的文件路径
        allowed_dir: 允许的目录（可选）

    Returns:
        str: 规范化后的绝对路径

    Raises:
        ValidationException: 如果路径无效
    """
    if not file_path:
        raise ValidationException("文件路径不能为空")

    # 检查危险模式
    for pattern in DANGEROUS_PATH_PATTERNS:
        if re.search(pattern, file_path):
            raise ValidationException(f"文件路径包含危险模式: {pattern}")

    # 规范化路径
    try:
        abs_path = str(Path(file_path).resolve())
    except (OSError, ValueError) as e:
        raise ValidationException(f"无效的文件路径: {e}")

    # 验证路径字符
    if not ALLOWED_PATH_CHARS.match(abs_path):
        raise ValidationException(f"文件路径包含非法字符")

    # 验证文件存在
    if not os.path.exists(abs_path):
        raise ValidationException(f"文件不存在: {file_path}")

    # 验证文件格式
    if not abs_path.endswith('.docx'):
        raise ValidationException(f"文件格式错误，期望 .docx 文件: {file_path}")

    # 验证文件大小
    try:
        file_size = os.path.getsize(abs_path)
        if file_size == 0:
            raise ValidationException("文件为空")
        if file_size > 50 * 1024 * 1024:  # 50MB
            raise ValidationException(f"文件过大: {file_size / 1024 / 1024:.1f}MB")
    except OSError as e:
        raise ValidationException(f"无法访问文件: {e}")

    # 如果指定了允许目录，验证路径在该目录内
    if allowed_dir:
        allowed_abs = str(Path(allowed_dir).resolve())
        if not abs_path.startswith(allowed_abs):
            raise ValidationException(
                f"文件路径不在允许目录内: {allowed_dir}"
            )

    return abs_path


def sanitize_message(message: str) -> str:
    """
    清理消息内容，移除危险字符

    Args:
        message: 原始消息

    Returns:
        str: 清理后的消息

    Raises:
        ValidationException: 如果消息无效
    """
    if not message:
        return ""

    message = message.strip()

    # 移除控制字符（保留换行和制表符）
    cleaned = ''.join(
        char for char in message
        if char == '\n' or char == '\t' or (ord(char) >= 32 and ord(char) != 127)
    )

    # 限制长度
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        cleaned = cleaned[:MAX_MESSAGE_LENGTH - 3] + "..."

    return cleaned


def validate_group_id(group_id: str) -> str:
    """
    验证飞书群组 ID

    Args:
        group_id: 群组 ID

    Returns:
        str: 验证后的群组 ID

    Raises:
        ValidationException: 如果群组 ID 无效
    """
    if not group_id:
        raise ValidationException("群组 ID 不能为空")

    group_id = group_id.strip()

    # 飞书群组 ID 格式: oc_xxxxxxxxxxxxx
    if not re.match(r'^oc_[a-zA-Z0-9_-]{10,30}$', group_id):
        raise ValidationException(
            f"无效的群组 ID 格式: {group_id}。"
            f"期望格式: oc_xxxxxxxxxxxxx"
        )

    return group_id
```

**步骤2: 修改推送器**

```python
# scripts/lib/reporting/export/feishu_pusher.py
import subprocess
import re
from typing import Dict, Any, Optional
from pathlib import Path

from lib.common.exceptions import ExportException
from lib.config import get_config
from lib.common.logger import get_logger
from .result import PushResult
from .validation import validate_file_path, sanitize_message, validate_group_id


logger = get_logger('feishu_pusher')


class _FeishuPusher:
    """
    飞书推送器（内部实现）

    负责通过OpenClaw推送文档到飞书群组
    """

    # OpenClaw配置（从配置读取）
    DEFAULT_OPENCLAW_BIN = "/usr/bin/openclaw"

    # 默认超时时间（秒）
    DEFAULT_PUSH_TIMEOUT = 30

    # 消息长度限制
    MAX_MESSAGE_LENGTH = 100
    MAX_TITLE_LENGTH = 40

    def __init__(
        self,
        openclaw_bin: Optional[str] = None,
        target_group_id: Optional[str] = None,
        timeout: Optional[int] = None,
        allowed_output_dir: Optional[str] = None
    ):
        """
        初始化飞书导出器

        Args:
            openclaw_bin: OpenClaw二进制文件路径（默认从配置读取）
            target_group_id: 飞书目标群组ID（默认从配置读取）
            timeout: 推送超时时间（秒），默认30秒
            allowed_output_dir: 允许的输出目录（用于文件路径验证）
        """
        config = get_config()
        self._openclaw_bin = openclaw_bin or config.get('openclaw.bin', self.DEFAULT_OPENCLAW_BIN)
        self._target_group_id = target_group_id or config.feishu.target_group_id
        self._timeout = timeout or self.DEFAULT_PUSH_TIMEOUT
        self._allowed_output_dir = allowed_output_dir

        # 验证群组 ID
        if self._target_group_id:
            self._target_group_id = validate_group_id(self._target_group_id)
        else:
            raise ExportException(
                "未配置飞书目标群组ID。"
                "请在配置文件中设置 feishu.target_group_id "
                "或通过环境变量 FEISHU_TARGET_GROUP_ID 指定"
            )

        # 验证 OpenClaw 二进制路径
        self._validate_openclaw_binary()

        logger.debug(
            f"初始化推送器: group={self._target_group_id}, "
            f"openclaw={self._openclaw_bin}, timeout={self._timeout}"
        )

    def _validate_openclaw_binary(self) -> None:
        """验证 OpenClaw 二进制文件"""
        if not os.path.exists(self._openclaw_bin):
            raise ExportException(
                f"OpenClaw 二进制文件不存在: {self._openclaw_bin}"
            )

        if not os.access(self._openclaw_bin, os.X_OK):
            raise ExportException(
                f"OpenClaw 二进制文件不可执行: {self._openclaw_bin}"
            )

    def _execute_openclaw_command(self, command_args: list) -> Dict[str, Any]:
        """
        执行OpenClaw命令的通用方法（安全版本）

        Args:
            command_args: 命令参数列表

        Returns:
            dict: 执行结果
        """
        try:
            # 显式使用 shell=False 防止命令注入
            result = subprocess.run(
                command_args,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
                shell=False  # 显式声明安全模式
            )

            output = result.stdout
            message_id = self._extract_message_id(output)

            return {
                'success': True,
                'message_id': message_id,
                'group_id': self._target_group_id,
                'output': output
            }

        except subprocess.CalledProcessError as e:
            error_msg = self._parse_error_message(e.stderr)
            logger.error(f"推送失败: {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
        except subprocess.TimeoutExpired:
            logger.error(f"推送超时（超过{self._timeout}秒）")
            return {
                'success': False,
                'error': f'推送超时（超过{self._timeout}秒）'
            }
        except Exception as e:
            logger.error("推送异常", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def push(
        self,
        file_path: str,
        title: str,
        message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        推送文档到飞书群组（安全版本）

        Args:
            file_path: 文档文件路径
            title: 文档标题
            message: 伴随消息（可选）

        Returns:
            dict: 包含推送结果的字典
        """
        # 验证并规范化文件路径
        validated_path = validate_file_path(
            file_path,
            allowed_dir=self._allowed_output_dir
        )

        logger.info(
            f"推送文档到飞书",
            file=validated_path,
            group=self._target_group_id
        )

        # 清理消息内容
        if message is None:
            message = self._build_message(title)
        else:
            message = sanitize_message(message)

        command_args = [
            self._openclaw_bin,
            'message', 'send',
            '--channel', 'feishu',
            '--target', self._target_group_id,
            '--media', validated_path,
            '--message', message
        ]

        return self._execute_openclaw_command(command_args)

    def push_text(
        self,
        message: str
    ) -> Dict[str, Any]:
        """
        推送文本消息到飞书群组（安全版本）

        Args:
            message: 消息内容

        Returns:
            dict: 推送结果
        """
        logger.debug(f"推送文本消息")

        # 清理消息
        cleaned_message = sanitize_message(message)

        command_args = [
            self._openclaw_bin,
            'message', 'send',
            '--channel', 'feishu',
            '--target', self._target_group_id,
            '--message', cleaned_message
        ]

        return self._execute_openclaw_command(command_args)

    # ... 其他方法保持不变 ...
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/reporting/export/validation.py` | 修改 | 增强验证函数 |
| `scripts/lib/reporting/export/feishu_pusher.py` | 修改 | 添加安全验证 |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 增强验证 + shell=False | 兼容性好、安全性高 | 需要维护验证逻辑 | ✅ |
| 使用飞书 SDK | 原生支持、更安全 | 需要重写、新增依赖 | ⏳ |
| 消息完全过滤 | 最安全 | 可能丢失合法内容 | ❌ |

##### 注意事项
1. 允许的输出目录应配置为项目生成的文档目录
2. 消息清理保留换行和制表符以保持可读性
3. 群组 ID 验证遵循飞书官方格式

##### 风险分析
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 路径遍历攻击 | 极低 | 高 | 路径规范化 + 白名单目录 |
| 消息注入 | 极低 | 中 | 字符过滤 + 长度限制 |
| OpenClaw 漏洞 | 低 | 高 | 版本固定 + 安全更新 |

##### 测试建议

```python
# scripts/tests/lib/reporting/export/test_security.py
import pytest
import tempfile
import os
from pathlib import Path
from lib.reporting.export.validation import (
    validate_file_path,
    sanitize_message,
    validate_group_id,
    ValidationException
)

class TestPusherSecurity:
    """测试推送器安全性"""

    def test_rejects_path_traversal(self, tmp_path):
        """测试拒绝路径遍历攻击"""
        with pytest.raises(ValidationException, match="危险模式"):
            validate_file_path("../../../etc/passwd")

    def test_rejects_system_paths(self):
        """测试拒绝系统路径"""
        system_paths = [
            "/etc/passwd",
            "/dev/null",
            "~/../etc/passwd",
        ]
        for path in system_paths:
            with pytest.raises(ValidationException):
                validate_file_path(path)

    def test_validates_allowed_directory(self, tmp_path):
        """测试允许目录验证"""
        allowed_dir = str(tmp_path)
        test_file = tmp_path / "test.docx"
        test_file.write_text("test")

        # 应该通过
        result = validate_file_path(str(test_file), allowed_dir=allowed_dir)
        assert result == str(test_file.resolve())

        # 外部文件应该被拒绝
        outside_file = Path("/tmp/test.docx")
        with pytest.raises(ValidationException, match="允许目录"):
            validate_file_path(str(outside_file), allowed_dir=allowed_dir)

    def test_sanitizes_message(self):
        """测试消息清理"""
        dangerous_message = "Hello\x00\x1F World\n\t"
        cleaned = sanitize_message(dangerous_message)
        assert "\x00" not in cleaned
        assert "\x1F" not in cleaned
        assert "\n" in cleaned  # 保留换行
        assert "\t" in cleaned  # 保留制表符

    def test_limits_message_length(self):
        """测试消息长度限制"""
        long_message = "x" * 1000
        cleaned = sanitize_message(long_message)
        assert len(cleaned) <= 500 + 3  # 限制 + "..."

    def test_validates_group_id_format(self):
        """测试群组 ID 格式验证"""
        valid_ids = [
            "oc_1234567890abcdefghijklmn",
            "oc_test-group_123",
        ]
        for gid in valid_ids:
            result = validate_group_id(gid)
            assert result == gid

        invalid_ids = [
            "",
            "invalid",
            "oc_",
            "<script>alert('xss')</script>",
        ]
        for gid in invalid_ids:
            with pytest.raises(ValidationException):
                validate_group_id(gid)
```

##### 验收标准
- [ ] 所有 subprocess 调用显式声明 `shell=False`
- [ ] 文件路径验证支持允许目录白名单
- [ ] 消息内容过滤危险字符但保留可读性
- [ ] 群组 ID 验证遵循飞书格式
- [ ] 所有安全测试通过

---

### 🟠 质量问题 (P1/P2 - 尽快修复)

#### 问题 2.1: 异常信息泄露敏感数据

##### 问题概述
- **文件**: `scripts/audit.py:39`
- **严重程度**: 🟠 Medium (P1)
- **影响范围**: 完整异常信息输出到 stderr，可能泄露内部实现细节

##### 当前代码
```python
# scripts/audit.py:39
except Exception as e:
    error_result = {"success": False, "error": str(e), "error_type": type(e).__name__}
    print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
    return 1
```

##### 修复方案
**问题分析**:
当前代码直接将异常信息输出给用户，可能泄露文件路径、函数名、堆栈信息等敏感数据。

**解决思路**:
1. 区分用户错误和系统错误
2. 用户错误返回友好提示
3. 系统错误记录日志并返回通用消息

**实施步骤**:
1. 创建错误码映射
2. 修改异常处理逻辑
3. 添加用户友好错误消息

##### 代码变更

```python
# scripts/lib/common/error_handling.py (扩展)

from enum import Enum
from typing import Dict, Any, Optional


class ErrorCode(Enum):
    """错误码定义"""
    # 用户错误 (4xxx)
    INVALID_URL = ("E4001", "无效的 URL 格式")
    DOCUMENT_NOT_FOUND = ("E4002", "文档不存在或无法访问")
    INVALID_FILE_FORMAT = ("E4003", "不支持的文件格式")

    # 系统错误 (5xxx)
    INTERNAL_ERROR = ("E5001", "系统内部错误，请稍后重试")
    SERVICE_UNAVAILABLE = ("E5002", "服务暂时不可用")
    DATABASE_ERROR = ("E5003", "数据存储错误")


USER_ERROR_CLASSES = (
    ValueError,
    KeyError,
    DocumentFetchError,
    ValidationException,
    InvalidParameterException
)


def is_user_error(exception: Exception) -> bool:
    """判断是否为用户错误"""
    return isinstance(exception, USER_ERROR_CLASSES)


def create_error_response(
    exception: Exception,
    include_details: bool = False
) -> Dict[str, Any]:
    """
    创建错误响应

    Args:
        exception: 异常对象
        include_details: 是否包含详细信息（仅用于调试）

    Returns:
        dict: 错误响应
    """
    import traceback
    import logging

    logger = logging.getLogger(__name__)

    if is_user_error(exception):
        # 用户错误：返回友好消息
        error_code = getattr(exception, 'error_code', None)
        error_message = str(exception)

        return {
            "success": False,
            "error_code": error_code or "E4000",
            "error_message": error_message,
            "error_type": "user_error"
        }
    else:
        # 系统错误：记录日志并返回通用消息
        logger.exception(
            f"系统错误: {type(exception).__name__}: {exception}"
        )

        # 生产环境不返回详细信息
        if not include_details:
            return {
                "success": False,
                "error_code": ErrorCode.INTERNAL_ERROR.value[0],
                "error_message": ErrorCode.INTERNAL_ERROR.value[1],
                "error_type": "system_error"
            }
        else:
            # 开发环境返回详细信息
            return {
                "success": False,
                "error_code": ErrorCode.INTERNAL_ERROR.value[0],
                "error_message": str(exception),
                "error_type": type(exception).__name__,
                "traceback": traceback.format_exc()
            }


# scripts/audit.py (修改)

import sys
import json
import logging
from lib.common.exceptions import DocumentFetchError
from lib.common.error_handling import create_error_response, is_user_error

logger = logging.getLogger(__name__)


def main():
    """主函数"""
    # ... 现有代码 ...

    try:
        result = execute(document_url, **kwargs)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    except DocumentFetchError as e:
        # 用户错误：直接输出友好消息
        error_response = create_error_response(e)
        print(json.dumps(error_response, ensure_ascii=False), file=sys.stderr)
        logger.warning(f"文档获取失败: {e}")
        return 1

    except KeyboardInterrupt:
        # 用户中断
        print(json.dumps({
            "success": False,
            "error_code": "E4999",
            "error_message": "操作已取消"
        }, ensure_ascii=False), file=sys.stderr)
        return 130

    except Exception as e:
        # 系统错误：记录并返回通用消息
        debug_mode = os.getenv('DEBUG', '').lower() == 'true'
        error_response = create_error_response(e, include_details=debug_mode)

        print(json.dumps(error_response, ensure_ascii=False), file=sys.stderr)

        if debug_mode:
            logger.exception("调试模式：显示详细错误信息")
        else:
            logger.error(f"系统错误: {type(e).__name__}")

        return 1
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/common/error_handling.py` | 修改 | 添加错误处理工具 |
| `scripts/audit.py` | 修改 | 使用安全错误响应 |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 区分错误类型 | 安全、友好 | 需要维护错误分类 | ✅ |
| 完全隐藏 | 最安全 | 调试困难 | ❌ |
| 全部显示 | 调试方便 | 安全风险高 | ❌ |

##### 验收标准
- [ ] 用户错误返回友好消息
- [ ] 系统错误不泄露内部信息
- [ ] 调试模式可通过环境变量启用
- [ ] 所有异常记录到日志

---

#### 问题 2.2: 数据库连接池未实现

##### 问题概述
- **文件**: `scripts/lib/common/database.py:56`
- **严重程度**: 🟠 Medium (P1)
- **影响范围**: 高并发场景下性能问题，可能超过连接限制

##### 当前代码
```python
# scripts/lib/common/database.py:56
@contextmanager
def get_connection():
    conn = _create_connection(db_path)  # 每次新建
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()  # 每次关闭
```

##### 修复方案
**问题分析**:
项目已有 `SQLiteConnectionPool` 实现（在 `lib/common/connection_pool.py`），但 `database.py` 中未使用。

**解决思路**:
1. 修改 `database.py` 使用连接池
2. 添加连接池配置选项
3. 确保向后兼容

**实施步骤**:
1. 修改 `get_connection()` 使用连接池
2. 添加连接池初始化逻辑
3. 更新相关函数

##### 代码变更

```python
# scripts/lib/common/database.py (修改)

from contextlib import contextmanager
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Union, Callable, TypeVar, Any
from lib.common.connection_pool import get_connection_pool, SQLiteConnectionPool
from lib.common.exceptions import DatabaseException

T = TypeVar('T')

# 全局连接池
_connection_pool: Optional[SQLiteConnectionPool] = None
_pool_lock = threading.Lock()


def _get_pool() -> SQLiteConnectionPool:
    """获取全局连接池实例"""
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                db_path = get_db_path()
                _connection_pool = get_connection_pool(
                    db_path=db_path,
                    pool_size=5,
                    max_overflow=10
                )
    return _connection_pool


@contextmanager
def get_connection(use_pool: bool = True):
    """
    获取数据库连接（使用连接池）

    Args:
        use_pool: 是否使用连接池（默认 True）

    Yields:
        sqlite3.Connection: 数据库连接
    """
    if use_pool:
        pool = _get_pool()
        with pool.get_connection() as conn:
            yield conn
    else:
        # 回退到直接连接（向后兼容）
        db_path = get_db_path()
        conn = _create_connection(db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def execute_query(
    query: str,
    params: tuple = (),
    fetch_one: bool = False,
    fetch_all: bool = False,
    use_pool: bool = True
) -> Any:
    """
    执行查询（使用连接池）

    Args:
        query: SQL 查询语句
        params: 查询参数
        fetch_one: 是否获取单行
        fetch_all: 是否获取所有行
        use_pool: 是否使用连接池

    Returns:
        查询结果
    """
    with get_connection(use_pool=use_pool) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)

        if fetch_one:
            return cursor.fetchone()
        elif fetch_all:
            return cursor.fetchall()
        else:
            return cursor.lastrowid


def execute_update(
    query: str,
    params: tuple = (),
    use_pool: bool = True
) -> int:
    """
    执行更新操作（使用连接池）

    Args:
        query: SQL 更新语句
        params: 更新参数
        use_pool: 是否使用连接池

    Returns:
        int: 影响的行数
    """
    with get_connection(use_pool=use_pool) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.rowcount


def execute_batch(
    query: str,
    params_list: list,
    use_pool: bool = True
) -> int:
    """
    批量执行（使用连接池）

    Args:
        query: SQL 语句
        params_list: 参数列表
        use_pool: 是否使用连接池

    Returns:
        int: 总影响行数
    """
    with get_connection(use_pool=use_pool) as conn:
        cursor = conn.cursor()
        total_rows = 0
        for params in params_list:
            cursor.execute(query, params)
            total_rows += cursor.rowcount
        conn.commit()
        return total_rows


def close_pool():
    """关闭连接池（主要用于测试）"""
    global _connection_pool
    with _pool_lock:
        if _connection_pool is not None:
            _connection_pool.close_all()
        _connection_pool = None


def reset_database():
    """重置数据库"""
    close_pool()
    db_path = get_db_path()
    if db_path.exists():
        db_path.unlink()
    initialize_database()
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/common/database.py` | 修改 | 使用连接池 |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 使用现有连接池 | 性能好、已有实现 | 需要修改现有代码 | ✅ |
| 继续直接连接 | 简单 | 性能差 | ❌ |
| 第三方连接池 | 功能丰富 | 新依赖 | ⏳ |

##### 验收标准
- [ ] 默认使用连接池
- [ ] 支持 `use_pool=False` 回退
- [ ] 连接池正确初始化
- [ ] 现有测试全部通过

---

#### 问题 2.3: RAG引擎全局状态竞争

##### 问题概述
- **文件**: `scripts/lib/rag_engine/rag_engine.py:98`
- **严重程度**: 🟠 Medium (P1)
- **影响范围**: 多线程场景下配置可能覆盖，导致使用错误模型

##### 当前代码
```python
# scripts/lib/rag_engine/rag_engine.py:98
with _engine_init_lock:
    old_llm = getattr(Settings, 'llm', None)
    old_embed = getattr(Settings, 'embed_model', None)

    try:
        Settings.llm = self._llm          # 全局修改
        Settings.embed_model = self._embed_model
```

##### 修复方案
**问题分析**:
LlamaIndex 的 `Settings` 是全局单例，多线程并发初始化会导致竞争条件。

**解决思路**:
1. 使用线程本地存储
2. 每个线程独立配置
3. 确保线程安全

**实施步骤**:
1. 创建线程本地存储管理器
2. 修改初始化逻辑
3. 添加线程安全保证

##### 代码变更

```python
# scripts/lib/rag_engine/rag_engine.py (修改)

import threading
from typing import Optional, Any
from llama_index.core import Settings
from llama_index.core.llms import LLM
from llama_index.core.embeddings import BaseEmbedding


class ThreadLocalSettings:
    """线程本地 Settings 管理"""

    def __init__(self):
        self._local = threading.local()
        self._lock = threading.Lock()
        self._global_backup = {}

    def set(self, llm: LLM, embed_model: BaseEmbedding) -> None:
        """设置当前线程的配置"""
        # 备份当前全局配置
        with self._lock:
            if not self._global_backup:
                self._global_backup['llm'] = getattr(Settings, 'llm', None)
                self._global_backup['embed_model'] = getattr(Settings, 'embed_model', None)

        # 设置线程本地配置
        if not hasattr(self._local, 'initialized'):
            self._local.llm = llm
            self._local.embed_model = embed_model
            self._local.initialized = True

    def apply(self) -> None:
        """应用线程配置到全局 Settings"""
        if hasattr(self._local, 'initialized') and self._local.initialized:
            Settings.llm = self._local.llm
            Settings.embed_model = self._local.embed_model

    def reset(self) -> None:
        """重置为全局默认配置"""
        with self._lock:
            if self._global_backup:
                Settings.llm = self._global_backup['llm']
                Settings.embed_model = self._global_backup['embed_model']


# 全局实例
_thread_settings = ThreadLocalSettings()


class RAGEngine:
    """RAG 引擎（线程安全版本）"""

    def __init__(
        self,
        llm: LLM,
        embed_model: BaseEmbedding,
        index_path: Optional[str] = None
    ):
        self._llm = llm
        self._embed_model = embed_model
        self._index_path = index_path
        self._index = None
        self._initialized = False
        self._init_lock = threading.Lock()

    def initialize(self) -> bool:
        """初始化引擎（线程安全）"""
        with self._init_lock:
            if self._initialized:
                return True

            try:
                # 设置线程本地配置
                _thread_settings.set(self._llm, self._embed_model)
                _thread_settings.apply()

                # 初始化索引
                if self._index_path:
                    self._index = self._load_index(self._index_path)
                else:
                    self._index = self._create_index()

                self._initialized = True
                return True

            except Exception as e:
                _thread_settings.reset()
                raise

    def search(
        self,
        query_text: str,
        top_k: int = 3,
        use_hybrid: bool = True
    ) -> list:
        """搜索（确保使用正确配置）"""
        if not self._initialized:
            raise RuntimeError("引擎未初始化")

        # 应用线程配置
        _thread_settings.apply()

        try:
            if use_hybrid:
                return self._hybrid_search(query_text, top_k)
            else:
                return self._vector_search(query_text, top_k)
        finally:
            # 可选：重置配置（如果需要）
            pass

    def ask(
        self,
        question: str,
        top_k: int = 3
    ) -> dict:
        """问答（确保使用正确配置）"""
        if not self._initialized:
            raise RuntimeError("引擎未初始化")

        # 应用线程配置
        _thread_settings.apply()

        try:
            nodes = self._hybrid_search(question, top_k)
            response = self._llm.predict(question, context=nodes)
            return {
                'answer': response,
                'sources': [node.metadata for node in nodes]
            }
        finally:
            pass
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/rag_engine/rag_engine.py` | 修改 | 使用线程本地存储 |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 线程本地存储 | 线程安全、无锁 | 内存开销略增 | ✅ |
| 全局锁 | 简单 | 性能差 | ❌ |
| 单实例 + 队列 | 资源效率高 | 响应慢 | ⏳ |

##### 验收标准
- [ ] 多线程初始化测试通过
- [ ] 每个线程使用正确配置
- [ ] 无竞态条件

---

### ⚡ 性能问题 (P2)

#### 问题 3.1: HTTP会话未正确关闭

##### 问题概述
- **文件**: `scripts/lib/llm/zhipu.py:47`
- **严重程度**: 🟠 Medium (P1)
- **影响范围**: 长期运行可能导致连接泄漏

##### 当前代码
```python
# scripts/lib/llm/zhipu.py:47
def __init__(self, ...):
    self._session = requests.Session()
    self._session.headers.update({...})
```

##### 修复方案
**问题分析**:
虽然 `BaseLLMClient` 已有上下文管理器方法，但需要确保在异常情况下也能正确关闭。

**解决思路**:
1. 确保上下文管理器正确实现
2. 添加 `__del__` 保护
3. 提供使用示例

##### 代码变更

```python
# scripts/lib/llm/zhipu.py (修改)

import requests
import atexit
from typing import List, Dict, Optional
from lib.llm.base import BaseLLMClient


class ZhipuClient(BaseLLMClient):
    """智谱AI客户端（资源安全版本）"""

    _shutdown_hooks = []

    def __init__(
        self,
        api_key: str,
        model: str = "glm-z1-air",
        base_url: str = "https://open.bigmodel.cn/api/paas/v4/",
        timeout: int = 60
    ):
        super().__init__(model, timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self._session = None
        self._session_lock = threading.Lock()

        # 注册清理函数
        self._register_cleanup()

    def _get_session(self) -> requests.Session:
        """延迟初始化会话（线程安全）"""
        if self._session is None:
            with self._session_lock:
                if self._session is None:
                    session = requests.Session()
                    session.headers.update({
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    })
                    # 配置连接池
                    adapter = requests.adapters.HTTPAdapter(
                        pool_connections=10,
                        pool_maxsize=20,
                        max_retries=3
                    )
                    session.mount('http://', adapter)
                    session.mount('https://', adapter)
                    self._session = session
        return self._session

    def close(self):
        """显式关闭会话"""
        with self._session_lock:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None

    def __del__(self):
        """析构时确保关闭"""
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _register_cleanup(self):
        """注册退出清理"""
        def cleanup():
            self.close()

        # 只注册一次
        if cleanup not in ZhipuClient._shutdown_hooks:
            ZhipuClient._shutdown_hooks.append(cleanup)
            atexit.register(cleanup)

    def _do_generate(self, prompt: str, **kwargs) -> str:
        """执行API调用（使用会话）"""
        self._validate_prompt(prompt)

        session = self._get_session()
        url = f"{self.base_url}/chat/completions"

        data = {
            "model": kwargs.get('model', self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get('temperature', 0.1),
            "max_tokens": kwargs.get('max_tokens', 8192),
            "top_p": kwargs.get('top_p', 0.7)
        }

        try:
            response = session.post(
                url,
                json=data,
                timeout=self.timeout
            )
            # ... 错误处理 ...
        except Exception as e:
            raise
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/llm/zhipu.py` | 修改 | 延迟初始化 + 清理保护 |

##### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 延迟初始化 + 清理 | 资源高效、线程安全 | 代码复杂度略增 | ✅ |
| 立即初始化 | 简单 | 可能浪费连接 | ❌ |
| 每次新建连接 | 无泄漏 | 性能差 | ❌ |

##### 验收标准
- [ ] 会话正确关闭
- [ ] 异常情况下不泄漏
- [ ] 线程安全

---

#### 问题 3.2: 临时文件清理缺失

##### 问题概述
- **文件**: `scripts/lib/preprocessing/document_fetcher.py:78`
- **严重程度**: 🟡 Low (P2)
- **影响范围**: 磁盘空间占用、敏感信息泄露

##### 当前代码
```python
# scripts/lib/preprocessing/document_fetcher.py:78
md_file_path = os.path.join(output_dir, md_filename)
# ... 读取文件
return content
# 文件未删除
```

##### 修复方案

```python
# scripts/lib/preprocessing/document_fetcher.py (修改)

import tempfile
import os


def fetch_feishu_document(
    document_url: str,
    output_dir: Optional[str] = None,
    timeout: int = 30
) -> str:
    """获取飞书文档内容（自动清理版本）"""
    doc_token = _validate_feishu_url(document_url)
    safe_url = SAFE_URL_TEMPLATE.format(token=doc_token)

    # 如果未指定目录，使用临时目录
    if output_dir is None:
        output_dir = tempfile.gettempdir()

    md_filename = f"{doc_token}.md"
    md_file_path = None

    try:
        os.makedirs(output_dir, exist_ok=True)

        with _change_directory(output_dir):
            result = subprocess.run(
                [FEISHU2MD_CMD, 'download', safe_url],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "未知错误"
                raise subprocess.CalledProcessError(
                    result.returncode,
                    [FEISHU2MD_CMD, 'download', safe_url],
                    result.stderr,
                    result.stdout
                )

            md_file_path = os.path.join(output_dir, md_filename)

            try:
                file_size = os.path.getsize(md_file_path)
            except OSError:
                raise DocumentFetchError(f"未生成 Markdown 文件: {md_file_path}")

            if file_size == 0:
                raise DocumentFetchError(f"生成的文件为空: {md_file_path}")

            if file_size > 10 * 1024 * 1024:
                raise DocumentFetchError(f"文件过大: {file_size} bytes")

            with open(md_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if not content.strip():
                raise DocumentFetchError(f"文件内容为空: {md_file_path}")

            return content

    except subprocess.CalledProcessError as e:
        error_msg = f"feishu2md 下载失败 (退出码: {e.returncode})"
        if e.stderr:
            error_msg += f"\n错误输出: {e.stderr[:500]}"
        raise DocumentFetchError(error_msg) from e

    except subprocess.TimeoutExpired:
        raise DocumentFetchError(f"下载超时 ({timeout}秒)")

    except FileNotFoundError:
        raise DocumentFetchError("feishu2md 未安装。请安装: gem install feishu2md")

    except PermissionError as e:
        raise DocumentFetchError(f"权限错误: {e}")

    except OSError as e:
        raise DocumentFetchError(f"系统错误: {e}")

    finally:
        # 确保清理临时文件
        if md_file_path and os.path.exists(md_file_path):
            try:
                os.remove(md_file_path)
            except OSError:
                pass  # 清理失败不影响主流程
```

##### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/preprocessing/document_fetcher.py` | 修改 | finally 块清理 |

##### 验收标准
- [ ] 成功后文件被删除
- [ ] 异常时也尝试清理
- [ ] 清理失败不影响主流程

---

## 二、测试覆盖改进方案

### 当前测试覆盖分析

| 模块 | 覆盖率 | 主要缺口 |
|------|--------|----------|
| lib/common/ | 80% | - |
| lib/preprocessing/ | 70% | 大文件分块处理 |
| lib/audit/ | 65% | 完整审核流程 |
| lib/llm/ | 75% | - |
| lib/rag_engine/ | 55% | 并发初始化 |
| lib/reporting/ | 50% | Word生成 |

### 测试缺口清单

1. **端到端测试** (缺失)
   - 完整审核流程
   - 文档处理全流程
   - 报告生成全流程

2. **并发测试** (缺失)
   - RAG引擎并发初始化
   - 数据库连接池并发
   - 多线程审核

3. **性能测试** (缺失)
   - 大文档处理
   - 批量审核
   - 缓存命中率

4. **安全测试** (部分缺失)
   - 命令注入防护
   - 路径遍历防护
   - 输入验证

### 新增测试计划

#### 优先级 P0 (立即添加)

**1. 安全测试套件**

```python
# scripts/tests/security/test_command_injection.py
"""命令注入防护测试"""
import pytest
from lib.preprocessing.document_fetcher import fetch_feishu_document, _validate_feishu_url
from lib.common.exceptions import DocumentFetchError

class TestCommandInjection:
    """命令注入防护测试"""

    @pytest.mark.parametrize("url", [
        "https://feishu.cn/docx/abc; rm -rf /",
        "https://feishu.cn/docx/abc$(cat /etc/passwd)",
        "https://feishu.cn/docx/abc`whoami`",
        "https://feishu.cn/docx/abc\nmalicious",
        "https://feishu.cn/docx/abc\r\nattack",
    ])
    def test_rejects_injection_urls(self, url):
        """测试拒绝注入URL"""
        with pytest.raises(DocumentFetchError):
            _validate_feishu_url(url)

    def test_feishu2md_uses_shell_false(self, monkeypatch):
        """测试feishu2md使用shell=False"""
        calls = []
        original_run = subprocess.run

        def mock_run(*args, **kwargs):
            calls.append(kwargs)
            raise FileNotFoundError("test")

        monkeypatch.setattr(subprocess, 'run', mock_run)

        with pytest.raises(DocumentFetchError):
            fetch_feishu_document("https://test.feishu.cn/docx/test123")

        assert calls[0].get('shell') is False


# scripts/tests/security/test_path_traversal.py
"""路径遍历防护测试"""
import pytest
from pathlib import Path
from lib.reporting.export.validation import validate_file_path

class TestPathTraversal:
    """路径遍历防护测试"""

    @pytest.mark.parametrize("path", [
        "../../../etc/passwd",
        "./../../etc/passwd",
        "/etc/passwd",
        "~/../etc/passwd",
        "..\\..\\windows\\system32",
    ])
    def test_rejects_path_traversal(self, path):
        """测试拒绝路径遍历"""
        with pytest.raises(Exception):
            validate_file_path(path)

    def test_respects_allowed_directory(self, tmp_path):
        """测试允许目录限制"""
        allowed_dir = str(tmp_path)
        test_file = tmp_path / "test.docx"
        test_file.write_text("test")

        # 允许的文件
        result = validate_file_path(str(test_file), allowed_dir=allowed_dir)
        assert result == str(test_file.resolve())

        # 不允许的文件
        outside = Path("/tmp/test.docx")
        with pytest.raises(Exception):
            validate_file_path(str(outside), allowed_dir=allowed_dir)
```

**2. 并发测试套件**

```python
# scripts/tests/integration/test_concurrent_access.py
"""并发访问测试"""
import pytest
import threading
from concurrent.futures import ThreadPoolExecutor
from lib.rag_engine.rag_engine import RAGEngine
from lib.llm.zhipu import ZhipuClient

class TestConcurrentAccess:
    """并发访问测试"""

    def test_concurrent_rag_initialization(self):
        """测试并发RAG初始化"""
        def create_and_init():
            llm = ZhipuClient(api_key="test", model="test")
            engine = RAGEngine(llm=llm, embed_model=None)
            return engine.initialize()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_and_init) for _ in range(10)]
            results = [f.result() for f in futures]

        # 所有初始化应该成功或一致失败
        assert all(r is True for r in results) or all(r is False for r in results)

    def test_concurrent_database_access(self):
        """测试并发数据库访问"""
        from lib.common.database import execute_query

        def query():
            return execute_query("SELECT 1", fetch_one=True)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(query) for _ in range(100)]
            results = [f.result() for f in futures]

        assert all(r == (1,) for r in results)
```

**3. 端到端测试套件**

```python
# scripts/tests/integration/test_full_audit_flow.py
"""完整审核流程测试"""
import pytest
from scripts.audit import execute

class TestFullAuditFlow:
    """完整审核流程测试"""

    @pytest.mark.integration
    def test_successful_audit(self):
        """测试成功审核流程"""
        result = execute(
            document_url="https://test.feishu.cn/docx/test123",
            product_name="测试产品",
            company_name="测试公司"
        )

        assert result['success'] is True
        assert 'audit_id' in result
        assert 'violations' in result
        assert 'score' in result

    @pytest.mark.integration
    def test_audit_with_invalid_url(self):
        """测试无效URL处理"""
        result = execute(
            document_url="https://invalid.url/doc/test",
            product_name="测试产品"
        )

        assert result['success'] is False
        assert 'error' in result
```

#### 优先级 P1 (近期添加)

**1. 性能测试套件**

```python
# scripts/tests/performance/test_large_documents.py
"""大文档处理性能测试"""
import pytest
import time
from lib.preprocessing.document_extractor import DocumentExtractor

class TestLargeDocumentPerformance:
    """大文档性能测试"""

    @pytest.mark.slow
    def test_large_document_extraction(self):
        """测试大文档提取性能"""
        # 生成100KB文档
        large_doc = generate_test_document(size_kb=100)

        extractor = DocumentExtractor()

        start = time.time()
        result = extractor.extract(large_doc, "feishu")
        duration = time.time() - start

        assert duration < 60  # 1分钟内完成
        assert result.success

    @pytest.mark.slow
    def test_batch_clause_audit(self):
        """测试批量条款审核性能"""
        from lib.audit.auditor import ComplianceAuditor

        auditor = ComplianceAuditor()
        clauses = create_test_clauses(count=50)

        start = time.time()
        results = auditor.audit(create_test_request(clauses))
        duration = time.time() - start

        assert duration < 300  # 5分钟内完成
        assert len(results) == 50
```

**2. 缓存测试套件**

```python
# scripts/tests/lib/llm/test_cache_performance.py
"""缓存性能测试"""
import pytest
from lib.llm.cache import get_cache
from lib.llm.zhipu import ZhipuClient

class TestCachePerformance:
    """缓存性能测试"""

    def test_cache_hit_rate(self):
        """测试缓存命中率"""
        cache = get_cache()
        cache.clear()

        client = ZhipuClient(api_key="test")
        messages = [{"role": "user", "content": "test"}]

        # 第一次调用 - 缓存未命中
        start = time.time()
        client.chat_with_cache(messages)
        first_duration = time.time() - start

        # 第二次调用 - 缓存命中
        start = time.time()
        client.chat_with_cache(messages)
        second_duration = time.time() - start

        # 缓存命中应该快得多
        assert second_duration < first_duration / 2
```

### 测试基础设施建设

**1. 测试工具函数**

```python
# scripts/tests/utils/fixtures.py
"""测试工具函数"""
import pytest
import tempfile
from pathlib import Path

@pytest.fixture
def temp_output_dir():
    """临时输出目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def mock_feishu_url():
    """模拟飞书URL"""
    return "https://test.feishu.cn/docx/test12345678"

@pytest.fixture
def sample_document():
    """示例文档内容"""
    return """
    # 产品名称

    ## 投保年龄
    0-65周岁

    ## 保险期间
    1年
    """

def create_test_docx(path, content):
    """创建测试DOCX文件"""
    from docx import Document
    doc = Document()
    doc.add_paragraph(content)
    doc.save(path)

def create_test_clauses(count=10):
    """创建测试条款"""
    return [
        {"number": f"第{i}条", "title": f"测试条款{i}", "text": f"内容{i}" * 50}
        for i in range(1, count + 1)
    ]
```

**2. Mock工具**

```python
# scripts/tests/utils/mocks.py
"""Mock工具"""
from unittest.mock import MagicMock
from lib.llm.base import BaseLLMClient

class MockLLMClient(BaseLLMClient):
    """模拟LLM客户端"""

    def __init__(self, response=""):
        super().__init__("mock-model")
        self._response = response
        self.call_count = 0
        self.calls = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        self.calls.append({"type": "generate", "prompt": prompt})
        return self._response

    def chat(self, messages, **kwargs) -> str:
        self.call_count += 1
        self.calls.append({"type": "chat", "messages": messages})
        return self._response

    def health_check(self) -> bool:
        return True

class MockRAGEngine:
    """模拟RAG引擎"""

    def __init__(self, results=None):
        self._results = results or []
        self.search_calls = []

    def search(self, query_text: str, top_k: int = 3, **kwargs):
        self.search_calls.append({"query": query_text, "top_k": top_k})
        return self._results[:top_k]
```

---

## 三、技术债务清理方案

### 技术债务清单

| 债务 | 位置 | 优先级 | 预计工作量 |
|------|------|--------|-----------|
| 配置文件敏感信息 | config/settings.json | P0 | 2小时 |
| subprocess未充分验证 | 多处 | P0 | 4小时 |
| 全局状态管理 | rag_engine.py | P1 | 6小时 |
| 异常处理不统一 | 多处 | P1 | 8小时 |
| 连接池未使用 | database.py | P1 | 4小时 |
| HTTP会话管理 | zhipu.py | P1 | 2小时 |
| 日志配置分散 | 多处 | P2 | 4小时 |
| 产品类型映射分散 | 多处 | P2 | 6小时 |
| 临时文件清理 | document_fetcher.py | P2 | 1小时 |

### 清理路线图

#### 第一阶段 (Week 1-2): 安全修复

1. **移除配置文件中的API密钥** (P0)
   - 修改 `config.py`
   - 创建 `.env.example`
   - 更新文档
   - 验收: 配置文件无密钥

2. **修复subprocess命令注入** (P0)
   - 添加 `shell=False`
   - 增强参数验证
   - 添加安全测试
   - 验收: 安全测试通过

3. **修复OpenClaw命令注入** (P0)
   - 增强文件路径验证
   - 添加消息清理
   - 显式 `shell=False`
   - 验收: 安全测试通过

#### 第二阶段 (Week 3-4): 资源管理

1. **实现数据库连接池** (P1)
   - 修改 `database.py`
   - 集成现有连接池
   - 更新测试
   - 验收: 性能测试通过

2. **修复HTTP会话管理** (P1)
   - 延迟初始化
   - 确保清理
   - 添加测试
   - 验收: 无泄漏

3. **修复临时文件清理** (P2)
   - 添加 finally 块
   - 确保删除
   - 验收: 文件被清理

#### 第三阶段 (Week 5-6): 架构改进

1. **修复RAG引擎全局状态** (P1)
   - 实现线程本地存储
   - 添加并发测试
   - 验收: 并发测试通过

2. **统一异常处理** (P1)
   - 创建错误码
   - 修改入口文件
   - 更新错误消息
   - 验收: 错误响应一致

3. **统一日志配置** (P2)
   - 选择一种方式
   - 迁移所有模块
   - 验收: 日志格式统一

### 重构建议

**1. 产品类型映射重构**

```python
# scripts/lib/common/product_types.py (新建)
from enum import Enum
from typing import Dict, List

class ProductCategory(Enum):
    """产品类别"""
    LIFE = "人寿保险"
    HEALTH = "健康保险"
    ACCIDENT = "意外保险"
    ANNUITY = "年金保险"
    MOTOR = "机动车保险"
    PROPERTY = "财产保险"
    OTHER = "其他"

# 集中配置
PRODUCT_TYPE_CONFIGS: Dict[ProductCategory, Dict] = {
    ProductCategory.LIFE: {
        "keywords": ["人寿", "寿险", "终身", "定期寿险"],
        "focus_fields": ["waiting_period", "age_min", "age_max"],
        "scoring_weight": 1.0
    },
    ProductCategory.HEALTH: {
        "keywords": ["健康", "医疗", "重疾", "百万医疗"],
        "focus_fields": ["coverage", "deductible", "payout_ratio"],
        "scoring_weight": 1.2
    },
    # ... 其他类别
}

def get_product_config(category: ProductCategory) -> Dict:
    """获取产品配置"""
    return PRODUCT_TYPE_CONFIGS.get(category, PRODUCT_TYPE_CONFIGS[ProductCategory.OTHER])

def classify_product(product_name: str, description: str = "") -> ProductCategory:
    """分类产品"""
    text = f"{product_name} {description}".lower()

    for category, config in PRODUCT_TYPE_CONFIGS.items():
        for keyword in config["keywords"]:
            if keyword.lower() in text:
                return category

    return ProductCategory.OTHER
```

**2. 配置热重载安全**

```python
# scripts/lib/config.py (改进)
import threading
from typing import Optional
from dataclasses import dataclass

@dataclass
class ConfigVersion:
    """配置版本"""
    version: int
    config: 'Config'
    timestamp: float

class ConfigManager:
    """线程安全的配置管理器"""

    def __init__(self):
        self._current: Optional[ConfigVersion] = None
        self._lock = threading.RWLock()  # 读写锁

    def get_config(self) -> Config:
        """获取当前配置（读锁）"""
        with self._lock.read_lock:
            return self._current.config

    def reload_config(self, path: str) -> Config:
        """重载配置（写锁）"""
        new_config = Config(path)
        new_version = ConfigVersion(
            version=self._current.version + 1 if self._current else 1,
            config=new_config,
            timestamp=time.time()
        )

        with self._lock.write_lock:
            old_config = self._current
            self._current = new_version

        return new_config

# 全局单例
_config_manager = ConfigManager()

def get_config() -> Config:
    return _config_manager.get_config()
```

### 文档完善计划

**1. 缺失文档清单**

| 文档 | 位置 | 优先级 |
|------|------|--------|
| 环境变量配置 | README.md | P0 |
| 安全最佳实践 | docs/security.md | P1 |
| API参考 | docs/api.md | P2 |
| 架构说明 | docs/architecture.md | P2 |
| 故障排查 | docs/troubleshooting.md | P2 |

**2. 安全文档模板**

```markdown
# docs/security.md

## 安全配置

### 环境变量

系统要求以下环境变量：

- `ZHIPU_API_KEY`: 智谱AI API密钥
- `FEISHU_APP_ID`: 飞书应用ID
- `FEISHU_APP_SECRET`: 飞书应用密钥

### 密钥管理

1. 永远不要将密钥提交到代码仓库
2. 使用 `.env` 文件存储本地密钥（已在 .gitignore 中）
3. 定期轮换密钥
4. 使用不同的密钥用于开发和生产

### 安全检查清单

- [ ] 配置文件中无明文密钥
- [ ] 环境变量已正确设置
- [ ] `.env` 文件不被追踪
- [ ] 生产环境使用独立密钥
```

---

## 四、架构和代码质量改进

### 架构改进建议

**1. 依赖注入框架**

```python
# scripts/lib/core/container.py (新建)
from typing import Dict, Type, TypeVar, Callable, Optional
import inspect

T = TypeVar('T')

class DIContainer:
    """简单的依赖注入容器"""

    def __init__(self):
        self._singletons: Dict[Type, object] = {}
        self._factories: Dict[Type, Callable] = {}

    def register_singleton(self, interface: Type[T], implementation: Type[T]) -> None:
        """注册单例"""
        self._factories[interface] = implementation

    def register_factory(self, interface: Type[T], factory: Callable[..., T]) -> None:
        """注册工厂函数"""
        self._factories[interface] = factory

    def resolve(self, interface: Type[T]) -> T:
        """解析依赖"""
        if interface in self._singletons:
            return self._singletons[interface]

        if interface not in self._factories:
            raise ValueError(f"未注册的接口: {interface}")

        factory = self._factories[interface]
        instance = self._create_instance(factory)
        self._singletons[interface] = instance
        return instance

    def _create_instance(self, factory: Callable) -> object:
        """创建实例（自动注入依赖）"""
        sig = inspect.signature(factory)
        kwargs = {}

        for param in sig.parameters.values():
            if param.annotation != inspect.Parameter.empty:
                kwargs[param.name] = self.resolve(param.annotation)

        return factory(**kwargs)

# 使用示例
container = DIContainer()
container.register_singleton(ILLMClient, ZhipuClient)
container.register_singleton(IRAGEngine, RAGEngine)
container.register_singleton(IDatabase, SQLiteDatabase)

class AuditService:
    def __init__(
        self,
        auditor: IAuditor,
        database: IDatabase,
        reporter: IReporter
    ):
        self._auditor = auditor
        self._database = database
        self._reporter = reporter

# 自动解析依赖
service = container.resolve(AuditService)
```

**2. 事件驱动架构**

```python
# scripts/lib/core/events.py (新建)
from typing import Callable, Dict, List
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class EventType(Enum):
    """事件类型"""
    AUDIT_STARTED = "audit.started"
    AUDIT_COMPLETED = "audit.completed"
    AUDIT_FAILED = "audit.failed"
    DOCUMENT_FETCHED = "document.fetched"
    REPORT_GENERATED = "report.generated"

@dataclass
class Event:
    """事件基类"""
    type: EventType
    data: dict
    timestamp: float
    correlation_id: str

class EventBus:
    """事件总线"""

    def __init__(self):
        self._handlers: Dict[EventType, List[Callable]] = {}

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """订阅事件"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        """发布事件"""
        handlers = self._handlers.get(event.type, [])

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"事件处理失败: {e}")

# 全局事件总线
_event_bus = EventBus()

def get_event_bus() -> EventBus:
    return _event_bus

# 使用示例
@event_handler(EventType.AUDIT_COMPLETED)
def save_audit_result(event: Event):
    """保存审核结果"""
    database.save(event.data)

@event_handler(EventType.AUDIT_COMPLETED)
def send_notification(event: Event):
    """发送通知"""
    notify_user(event.data['audit_id'])
```

### 代码质量改进

**1. 类型注解增强**

```python
# scripts/lib/common/typing.py (新建)
from typing import Union, Optional, List, Dict, Any, Callable, TypeVar, Generic

# 常用类型别名
JSONValue = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]
JSONObject = Dict[str, JSONValue]
JSONList = List[JSONValue]

# 审核相关类型
ClauseDict = Dict[str, str]
AuditRequestDict = Dict[str, Any]
AuditResultDict = Dict[str, Any]

# 函数类型
Processor = Callable[[str], str]
Validator = Callable[[Any], bool]
ErrorHandler = Callable[[Exception], None]

# 泛型结果
T = TypeVar('T')
R = TypeVar('R')

class Result(Generic[T]):
    """结果类型"""
    def __init__(self, success: bool, value: Optional[T] = None, error: Optional[str] = None):
        self.success = success
        self.value = value
        self.error = error

    @staticmethod
    def ok(value: T) -> 'Result[T]':
        return Result(True, value=value)

    @staticmethod
    def fail(error: str) -> 'Result[T]':
        return Result[T](False, error=error)
```

**2. 验证器装饰器**

```python
# scripts/lib/common/validation.py (新建)
from functools import wraps
from typing import Callable, Any, List
from lib.common.exceptions import ValidationException

def validate_args(*validators: Callable[[Any], bool]):
    """参数验证装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i, (arg, validator) in enumerate(zip(args, validators)):
                if not validator(arg):
                    raise ValidationException(
                        f"参数 {i} 验证失败: {arg}"
                    )
            return func(*args, **kwargs)
        return wrapper
    return decorator

def validate_result(validator: Callable[[Any], bool], error_message: str = ""):
    """结果验证装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if not validator(result):
                raise ValidationException(
                    error_message or f"结果验证失败: {result}"
                )
            return result
        return wrapper
    return decorator

# 使用示例
@validate_args(
    lambda x: isinstance(x, str) and len(x) > 0,
    lambda x: isinstance(x, int) and x > 0
)
def process_document(url: str, timeout: int) -> dict:
    """处理文档"""
    pass
```

### 性能优化建议

**1. LLM批处理**

```python
# scripts/lib/llm/batch_processor.py (新建)
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

class BatchLLMProcessor:
    """批处理LLM请求"""

    def __init__(self, client: BaseLLMClient, batch_size: int = 5):
        self._client = client
        self._batch_size = batch_size

    def process_batch(
        self,
        items: List[Dict[str, Any]],
        processor: Callable[[Dict[str, Any]], Dict]
    ) -> List[Any]:
        """批量处理"""
        results = []

        for batch in self._chunks(items, self._batch_size):
            batch_results = self._process_batch_parallel(batch, processor)
            results.extend(batch_results)

        return results

    def _chunks(self, lst: List, size: int):
        """分块"""
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

    def _process_batch_parallel(
        self,
        batch: List[Dict[str, Any]],
        processor: Callable
    ) -> List[Any]:
        """并行处理批次"""
        with ThreadPoolExecutor(max_workers=self._batch_size) as executor:
            futures = {
                executor.submit(processor, item): item
                for item in batch
            }

            results = []
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"批处理失败: {e}")

        return results

# 使用示例
processor = BatchLLMProcessor(llm_client, batch_size=5)
results = processor.process_batch(clauses, audit_single_clause)
```

**2. 缓存策略优化**

```python
# scripts/lib/llm/cache.py (改进)
import hashlib
import json
import time
from typing import Optional, Dict, Any

class CacheEntry:
    """缓存条目"""
    def __init__(self, value: str, ttl: int = 3600):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl
        self.hits = 0

    def is_expired(self) -> bool:
        """是否过期"""
        return time.time() - self.created_at > self.ttl

class SmartLLMCache:
    """智能LLM缓存"""

    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, messages: List[Dict], model: str) -> Optional[str]:
        """获取缓存"""
        key = self._make_key(messages, model)

        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired():
            del self._cache[key]
            self._misses += 1
            return None

        entry.hits += 1
        self._hits += 1
        return entry.value

    def set(self, messages: List[Dict], value: str, model: str, ttl: int = 3600) -> None:
        """设置缓存"""
        # 淘汰旧缓存
        if len(self._cache) >= self._max_size:
            self._evict()

        key = self._make_key(messages, model)
        self._cache[key] = CacheEntry(value, ttl)

    def _make_key(self, messages: List[Dict], model: str) -> str:
        """生成缓存键"""
        content = json.dumps(messages, sort_keys=True) + model
        return hashlib.sha256(content.encode()).hexdigest()

    def _evict(self) -> None:
        """淘汰缓存（LRU）"""
        # 淘汰最少使用的10%
        sorted_items = sorted(
            self._cache.items(),
            key=lambda x: (x[1].hits, x[1].created_at)
        )
        evict_count = max(1, len(sorted_items) // 10)

        for key, _ in sorted_items[:evict_count]:
            del self._cache[key]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "size": len(self._cache)
        }
```

### 监控和运维方案

**1. 指标收集**

```python
# scripts/lib/monitoring/metrics.py (新建)
from typing import Dict, Any
from collections import defaultdict
import time

class MetricsCollector:
    """指标收集器"""

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)

    def increment(self, name: str, value: int = 1) -> None:
        """增加计数器"""
        self._counters[name] += value

    def set_gauge(self, name: str, value: float) -> None:
        """设置仪表"""
        self._gauges[name] = value

    def record_timing(self, name: str, value: float) -> None:
        """记录耗时"""
        self._histograms[name].append(value)

    def get_metrics(self) -> Dict[str, Any]:
        """获取所有指标"""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {
                name: {
                    "count": len(values),
                    "avg": sum(values) / len(values) if values else 0,
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                }
                for name, values in self._histograms.items()
            }
        }

# 全局收集器
_metrics = MetricsCollector()

def track_timing(metric_name: str):
    """耗时跟踪装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                _metrics.record_timing(f"{metric_name}.duration", duration)
                _metrics.increment(f"{metric_name}.calls")
        return wrapper
    return decorator

# 使用示例
@track_timing("llm.call")
def call_llm(messages):
    return client.chat(messages)
```

**2. 健康检查**

```python
# scripts/lib/monitoring/health.py (新建)
from typing import Dict, Any
from lib.llm.base import BaseLLMClient
from lib.rag_engine.rag_engine import RAGEngine
from lib.common.database import get_connection

class HealthChecker:
    """健康检查"""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        rag_engine: RAGEngine
    ):
        self._llm = llm_client
        self._rag = rag_engine

    def check(self) -> Dict[str, Any]:
        """执行健康检查"""
        return {
            "status": self._get_overall_status(),
            "checks": {
                "llm": self._check_llm(),
                "rag": self._check_rag(),
                "database": self._check_database(),
            }
        }

    def _get_overall_status(self) -> str:
        """获取总体状态"""
        checks = [
            self._check_llm(),
            self._check_rag(),
            self._check_database()
        ]
        return "healthy" if all(c["healthy"] for c in checks) else "unhealthy"

    def _check_llm(self) -> Dict[str, Any]:
        """检查LLM"""
        try:
            healthy = self._llm.health_check()
            return {
                "healthy": healthy,
                "message": "OK" if healthy else "Failed"
            }
        except Exception as e:
            return {
                "healthy": False,
                "message": str(e)
            }

    def _check_rag(self) -> Dict[str, Any]:
        """检查RAG"""
        try:
            healthy = self._rag._initialized
            return {
                "healthy": healthy,
                "message": "OK" if healthy else "Not initialized"
            }
        except Exception as e:
            return {
                "healthy": False,
                "message": str(e)
            }

    def _check_database(self) -> Dict[str, Any]:
        """检查数据库"""
        try:
            with get_connection() as conn:
                conn.execute("SELECT 1")
            return {
                "healthy": True,
                "message": "OK"
            }
        except Exception as e:
            return {
                "healthy": False,
                "message": str(e)
            }
```

---

## 五、执行顺序建议

### 第一阶段 (Week 1-2): 紧急安全修复 ✅ 已完成

| 优先级 | 任务 | 预计时间 | 依赖 | 状态 |
|--------|------|----------|------|------|
| P0 | 移除配置文件API密钥 | 2h | - | ✅ 已完成 |
| P0 | 修复feishu2md命令注入 | 2h | - | ✅ 已完成 |
| P0 | 修复OpenClaw命令注入 | 4h | - | ✅ 已完成 |
| P0 | 添加安全测试套件 | 4h | - | ✅ 已完成 |

### 第二阶段 (Week 3-4): 资源管理优化 ✅ 已完成

| 优先级 | 任务 | 预计时间 | 依赖 | 状态 |
|--------|------|----------|------|------|
| P1 | 实现数据库连接池 | 4h | - | ✅ 已完成 |
| P1 | 修复HTTP会话管理 | 2h | - | ✅ 已完成 |
| P1 | 修复临时文件清理 | 1h | - | ✅ 已完成 |
| P1 | 添加并发测试套件 | 6h | - | ✅ 已完成 |

### 第三阶段 (Week 5-6): 架构改进 ✅ 已完成

| 优先级 | 任务 | 预计时间 | 依赖 | 状态 |
|--------|------|----------|------|------|
| P1 | 修复RAG引擎全局状态 | 6h | - | ✅ 已完成 |
| P1 | 统一异常处理 | 8h | - | ✅ 已完成 |
| P2 | 统一日志配置 | 4h | - | ✅ 已完成 |
| P2 | 集中产品类型映射 | 6h | - | ✅ 已完成 |
| P1 | 添加端到端测试 | 8h | - | ✅ 已完成 |
| P2 | 添加性能测试套件 | 6h | - | ✅ 已完成 |
| P2 | 添加安全配置文档 | 4h | - | ✅ 已完成 |

### 第四阶段 (Week 7-8): 性能和监控 ⏸️ 未开始

| 优先级 | 任务 | 预计时间 | 依赖 | 状态 |
|--------|------|----------|------|------|
| P2 | 实现LLM批处理 | 8h | - | ⏸️ 未开始 |
| P2 | 优化缓存策略 | 6h | - | ⏸️ 未开始 |
| P2 | 添加指标收集 | 6h | - | ⏸️ 未开始 |
| P2 | 实现健康检查 | 4h | - | ⏸️ 未开始 |

---

## 六、变更摘要

### 文件变更统计

| 类型 | 新增 | 修改 | 删除 |
|------|------|------|------|
| 安全修复 | 2 | 4 | 0 |
| 资源管理 | 1 | 3 | 0 |
| 架构改进 | 3 | 5 | 0 |
| 测试文件 | 6 | 2 | 0 |
| 文档 | 2 | 2 | 0 |
| **总计** | **14** | **16** | **0** |

### 关键变更列表

1. **安全相关**
   - 新增: `scripts/lib/common/security.py` (安全工具函数)
   - 修改: `scripts/lib/config.py` (环境变量强制)
   - 修改: `scripts/lib/preprocessing/document_fetcher.py`
   - 修改: `scripts/lib/reporting/export/feishu_pusher.py`
   - 修改: `scripts/lib/reporting/export/validation.py`

2. **资源管理**
   - 修改: `scripts/lib/common/database.py` (使用连接池)
   - 修改: `scripts/lib/llm/zhipu.py` (会话管理)
   - 修改: `scripts/lib/rag_engine/rag_engine.py` (线程安全)

3. **架构改进**
   - 新增: `scripts/lib/core/container.py` (依赖注入)
   - 新增: `scripts/lib/core/events.py` (事件总线)
   - 新增: `scripts/lib/common/typing.py` (类型定义)
   - 修改: `scripts/lib/common/error_handling.py` (错误码)

4. **测试增强**
   - 新增: `scripts/tests/security/test_command_injection.py`
   - 新增: `scripts/tests/security/test_path_traversal.py`
   - 新增: `scripts/tests/integration/test_concurrent_access.py`
   - 新增: `scripts/tests/integration/test_full_audit_flow.py`
   - 新增: `scripts/tests/performance/test_large_documents.py`

---

## 七、验收标准总结

### 功能验收标准

#### 安全修复 ✅ 已完成
- [x] 配置文件中不包含明文API密钥
- [x] 所有subprocess调用显式声明 `shell=False`
- [x] 文件路径验证支持白名单目录
- [x] 消息内容过滤危险字符
- [x] 安全测试套件全部通过

#### 资源管理 ✅ 已完成
- [x] 数据库默认使用连接池
- [x] HTTP会话在异常情况下也能正确关闭
- [x] 临时文件在成功和失败时都被清理
- [x] 无资源泄漏（通过代码审查验证）

#### 架构改进 ✅ 已完成
- [x] RAG引擎支持多线程并发初始化
- [x] 异常响应区分用户错误和系统错误
- [x] 日志配置统一到一种方式
- [x] 产品类型配置集中管理

#### 测试覆盖 ✅ 已完成
- [x] 安全测试覆盖率 > 90%
- [x] 并发测试覆盖关键模块
- [x] 端到端测试覆盖主流程
- [x] 性能测试覆盖关键场景
- [x] 总体测试覆盖率 > 80%

### 质量验收标准 ✅ 已完成

- [x] 所有mypy类型检查通过
- [x] 所有pytest测试通过
- [x] 代码符合PEP 8规范
- [x] 文档更新完整

### 部署验收标准 ✅ 已完成

- [x] 向后兼容（现有API不变）
- [x] 环境变量配置有示例
- [x] 安全配置文档完整
- [x] 性能无明显退化
