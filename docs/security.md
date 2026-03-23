# 安全配置指南

本文档说明 Actuary Sleuth 系统的安全配置要求。

## 环境变量配置

系统要求以下环境变量用于敏感配置：

### 必需的环境变量

```bash
# 智谱 AI API 密钥（必需）
ZHIPU_API_KEY=your_zhipu_api_key_here

# 飞书应用配置（必需）
FEISHU_APP_ID=cli_your_app_id_here
FEISHU_APP_SECRET=your_app_secret_here
```

### 可选的环境变量

```bash
# OpenAI API 密钥（如使用 OpenAI）
OPENAI_API_KEY=your_openai_api_key_here

# OpenClaw 二进制路径
OPENCLAW_BIN=/usr/bin/openclaw

# 飞书目标群组 ID
FEISHU_TARGET_GROUP_ID=oc_your_group_id_here

# 调试模式
DEBUG=false
```

## 环境变量设置方式

### 方式 1: 使用 .env 文件（推荐用于开发）

1. 复制环境变量模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，填入实际的密钥：
```bash
ZHIPU_API_KEY=sk-your-actual-key-here
FEISHU_APP_ID=cli_your_actual_app_id
FEISHU_APP_SECRET=your_actual_secret
```

3. 确认 `.env` 文件已在 `.gitignore` 中，不会被提交到仓库

### 方式 2: 系统环境变量（推荐用于生产）

#### Linux / macOS
在 `~/.bashrc` 或 `~/.zshrc` 中添加：
```bash
export ZHIPU_API_KEY="your_key_here"
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_secret"
```

#### Windows
在系统环境变量中设置，或在 PowerShell 配置文件中添加：
```powershell
$env:ZHIPU_API_KEY="your_key_here"
$env:FEISHU_APP_ID="your_app_id"
$env:FEISHU_APP_SECRET="your_secret"
```

### 方式 3: Docker 容器环境变量

在 `docker-compose.yml` 中配置：
```yaml
services:
  actuary-sleuth:
    environment:
      - ZHIPU_API_KEY=${ZHIPU_API_KEY}
      - FEISHU_APP_ID=${FEISHU_APP_ID}
      - FEISHU_APP_SECRET=${FEISHU_APP_SECRET}
    env_file:
      - .env
```

## 密钥管理最佳实践

### 1. 永远不要将密钥提交到代码仓库

- ❌ 不要在配置文件中存储密钥
- ❌ 不要在代码中硬编码密钥
- ✅ 使用环境变量
- ✅ 使用密钥管理服务（生产环境推荐）

### 2. 密钥轮换

定期（建议每90天）轮换 API 密钥：

1. 在智谱AI平台生成新密钥
2. 更新环境变量
3. 验证新密钥正常工作
4. 撤销旧密钥

### 3. 密钥权限

- 确保密钥文件权限为 `600`（仅所有者可读写）
- 不要在日志中记录密钥
- 不要在错误消息中返回密钥

### 4. 不同环境使用不同密钥

```bash
# 开发环境使用测试密钥
export ZHIPU_API_KEY="dev_key_here"

# 生产环境使用生产密钥
export ZHIPU_API_KEY="prod_key_here"
```

## 安全检查清单

部署前检查：

- [ ] 配置文件（`scripts/config/settings.json`）中不包含任何明文密钥
- [ ] 环境变量已正确设置
- [ ] `.env` 文件已在 `.gitignore` 中
- [ ] 生产环境使用独立的密钥
- [ ] 密钥访问权限已正确配置
- [ ] 日志中不会记录敏感信息
- [ ] DEBUG 模式在生产环境已禁用

## 配置验证

系统启动时会验证必需的环境变量：

```bash
# 检查配置
python3 scripts/audit.py --help

# 如果缺少必需的环境变量，会看到类似错误：
# ConfigurationError: 智谱 API 密钥未设置。请设置环境变量 'ZHIPU_API_KEY'
```

## 故障排查

### 错误：API 密钥未设置

```
ConfigurationError: 智谱 AI API 密钥未设置。请设置环境变量 'ZHIPU_API_KEY'
```

**解决方案**：确保已设置 `ZHIPU_API_KEY` 环境变量

### 错误：飞书应用密钥未设置

```
ConfigurationError: 飞书 App Secret 未设置。请设置环境变量 'FEISHU_APP_SECRET'
```

**解决方案**：确保已设置 `FEISHU_APP_SECRET` 环境变量

### 错误：API 密钥格式无效

```
ConfigurationError: 智谱 API 密钥格式无效。密钥应以 'sk-' 或 'SDK' 开头
```

**解决方案**：检查密钥格式是否正确

## 安全审计

定期执行安全审计：

```bash
# 检查配置文件中是否包含密钥
grep -r "api_key\|app_secret\|API_KEY\|APP_SECRET" scripts/config/

# 应该只看到空值或占位符，不应该有实际密钥
```
