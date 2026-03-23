---
description: 根据research.md生成问题修复方案plan.md，包含详细说明、代码示例、文件路径、权衡考虑
arguments:
  - name: source
    description: 源文件路径（默认research.md）
    required: false
  - name: output
    description: 输出文件路径（默认plan.md）
    required: false
---

# Gen Plan - 问题修复方案生成器

根据 `research.md` 的全面分析，生成包含详细说明、代码示例、文件路径、权衡考虑的修复方案文档 `plan.md`。

## 核心要求

> **生成的 plan.md 应包含以下全部内容：**
> - 潜在问题列表的修复方案
> - 测试覆盖改进计划
> - 技术债务清理方案
> - 架构和代码质量改进建议
>
> **The generated plan always includes a detailed explanation of the approach, code snippets showing the actual changes, file paths that will be modified, and considerations and trade-offs.**

## 命令格式

```bash
/gen-plan [source] [output]
```

## 用法

```bash
/gen-plan                    # 基于 research.md 生成 plan.md
/gen-plan research.md        # 指定源文件
/gen-plan research.md fix.md # 指定源文件和输出文件
```

---

## 执行步骤

### 第一步：读取并解析 research.md

1. 读取 `research.md` 文件
2. 提取所有问题条目
3. 解析每个问题的：
   - 问题标题和描述
   - 文件路径和行号
   - 当前代码片段
   - 建议的解决方案

### 第二步：分析代码库

对于每个问题：
1. 读取问题所在文件
2. 分析相关代码上下文
3. 理解问题的根本原因
4. 评估修复影响范围

### 第三步：分析 research.md 内容结构

解析 research.md 识别包含的章节：
1. **潜在问题分析** - 如果存在，生成详细修复方案
2. **测试覆盖分析** - 如果存在，生成测试改进方案
3. **技术债务** - 如果存在，生成清理方案
4. **改进建议** - 如果存在，生成具体实施计划

### 第四步：生成针对性修复方案

**针对 research.md 中实际包含的内容，生成对应章节：**

#### 如果包含「潜在问题分析」

为每个问题生成：
1. **问题概述** - 文件路径、行号、严重程度、影响范围
2. **当前代码** - 完整的问题代码片段
3. **修复方案** - 问题分析、解决思路、实施步骤
4. **代码变更** - 完整可运行的修复代码（无省略）
5. **涉及文件** - 修改/新增/删除文件列表
6. **权衡考虑** - 3种方案对比（表格形式）
7. **注意事项** - 兼容性、性能、维护成本
8. **风险分析** - 风险列表、概率影响、缓解措施
9. **测试建议** - 测试策略、完整测试代码
10. **验收标准** - SMART 原则的可测量条件

#### 如果包含「测试覆盖分析」

生成：
1. **测试覆盖率详情** - 按 module 统计
2. **测试缺口清单** - 缺失测试的文件和功能
3. **新增测试计划** - 优先级排序的测试文件列表
4. **测试基础设施** - Mock/Fixture/工具函数需求

#### 如果包含「技术债务」

生成：
1. **债务清单** - 按优先级分类
2. **清理路线图** - 分阶段计划
3. **重构建议** - 具体重构方案
4. **文档完善** - 缺失文档列表

#### 如果包含「改进建议」

生成：
1. **架构改进** - 具体改进方案和代码示例
2. **代码质量** - 类型安全、异常处理等
3. **性能优化** - 瓶颈识别和优化方案
4. **监控运维** - 日志、指标、告警方案

### 第五步：生成文档

**根据 research.md 实际内容动态生成对应章节：**

1. **按问题优先级和类型分组**（P0 → P1 → P2 → P3，安全/质量/性能/设计）
2. **添加执行顺序建议**
3. **添加变更摘要**
4. **添加验收标准总结**
5. **输出到 `plan.md`**

---

## 输出格式规范

### 文档结构（动态生成）

```markdown
# 项目名称 - 综合改进方案

生成时间: YYYY-MM-DD
源文档: research.md

本方案基于 research.md 的分析内容生成，包含以下章节：

---

## 一、问题修复方案

*(仅当 research.md 包含「潜在问题分析」时生成此章节)*

### 🔴 安全问题 (P0/P1 - 必须修复)

#### 问题 1.1: [P1] 缺少输入验证
...（详细修复方案）

---

### ⚠️ 质量问题 (P1/P2 - 尽快修复)

#### 问题 2.1: [P1] 异常处理不够细致
...（详细修复方案）

---

### 🏗️ 设计缺陷 (P2)

#### 问题 3.1: [P2] 线程安全的全局配置
...（详细修复方案）

---

### ⚡ 性能问题 (P2)

#### 问题 4.1: [P2] 资源泄漏风险
...（详细修复方案）

---

## 二、测试覆盖改进方案

*(仅当 research.md 包含「测试覆盖分析」时生成此章节)*

### 当前测试覆盖分析
### 测试缺口清单
### 新增测试计划
### 测试基础设施建设

---

## 三、技术债务清理方案

*(仅当 research.md 包含「技术债务」时生成此章节)*

### 技术债务清单
### 清理路线图
### 重构建议
### 文档完善计划

---

## 四、架构和代码质量改进

*(仅当 research.md 包含「改进建议」时生成此章节)*

### 架构改进建议
### 代码质量改进
### 性能优化建议
### 监控和运维方案

---

## 附录

### 执行顺序建议
### 变更摘要
### 验收标准总结

#### 验收标准明细

##### 功能验收标准
- [ ] 基于实际修复方案的验收条件
- [ ] ...

##### 质量验收标准
- [ ] 测试覆盖率目标
- [ ] ...

##### 部署验收标准
- [ ] 向后兼容性验证
- [ ] ...
```

---

## 质量要求

### 代码示例
- ✅ 完整可运行，不使用 `...` 省略
- ✅ 包含必要的 import 语句
- ✅ 添加关键注释
- ✅ 遵循项目编码规范

### 权衡考虑
- ✅ 至少 3 种可行方案
- ✅ 表格形式展示
- ✅ 明确选择理由（✅/❌/⏳）

### 文件路径
- ✅ 使用项目相对路径
- ✅ 包含行号信息
- ✅ 明确修改/新增/删除

### 验收标准
- ✅ 具体可测量
- ✅ 符合 SMART 原则

---

## 示例输出片段

```markdown
### 问题 1.1: 命令注入风险修复

#### 问题概述
- **文件**: scripts/lib/preprocessing/document_fetcher.py:22-28
- **函数**: fetch_feishu_document()
- **严重程度**: 🔴 高危 (P0)
- **影响范围**: 安全漏洞，可能导致命令注入攻击

#### 当前代码
```python
# scripts/lib/preprocessing/document_fetcher.py:22-28
result = subprocess.run(
    ['feishu2md', 'download', document_url],
    capture_output=True,
    text=True,
    timeout=30,
    check=True
)
```

#### 修复方案
添加多层防御：URL 白名单验证、Token 格式验证、路径遍历防护...

#### 代码变更
```python
import re
import shlex

FEISHU_URL_PATTERN = re.compile(r'^https?://[a-zA-Z0-9.-]+\\.feishu\\.cn/docx/')
DOC_TOKEN_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{8,64}$')

def fetch_feishu_document(document_url: str) -> str:
    if not FEISHU_URL_PATTERN.match(document_url):
        raise DocumentFetchError("无效的飞书 URL 格式")
    # ... 完整实现
```

#### 权衡考虑
| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| 白名单验证 | 最安全 | 可能误杀合法 URL | ✅ |
| 黑名单过滤 | 灵活 | 难以覆盖所有攻击 | ❌ |
| SDK 替代 | 无注入风险 | 需要重写 | ⏳ |

#### 测试建议
```python
def test_command_injection_rejected():
    malicious_urls = [
        "https://feishu.cn/docx/abc; rm -rf /",
        "https://feishu.cn/docx/$(cat /etc/passwd)",
    ]
    for url in malicious_urls:
        with pytest.raises(DocumentFetchError):
            fetch_feishu_document(url)
```
```

---

## 注意事项

1. **分析代码库**: 必须实际读取相关文件，分析代码上下文
2. **完整代码**: 代码变更必须是完整的、可直接运行的，不使用省略号
3. **权衡分析**: 每个问题至少提供 3 种可行方案并说明选择理由
4. **测试代码**: 提供完整的测试代码示例
5. **遵循规范**: 遵循项目的编码规范（如 CLAUDE.md）

---

## 相关文件

- `research.md` - 问题研究报告（源）
- `plan.md` - 修复方案（输出）
- `CLAUDE.md` - 项目编码规范（参考）
