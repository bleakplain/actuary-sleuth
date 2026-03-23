---
description: 根据批注更新 plan.md 和 CLAUDE.md，提炼规则并移除批注内容
arguments:
  - name: action
    description: 操作类型：update/update-claude/review/rules
    required: true
  - name: file
    description: 文件路径（仅 review 操作需要）
    required: false
---

# Fix Plan - 文档更新工具

根据批注内容更新 plan.md 和 CLAUDE.md，提炼编码规则并移除所有批注。

## 命令格式

```bash
/fix-plan <action> [file]
```

## 可用操作

### 1. `/fix-plan update` - 更新文档

基于批注内容更新 plan.md，并将新规则提炼到 CLAUDE.md。

**用法**:
```bash
/fix-plan update
```

**执行步骤**:
1. 读取当前 plan.md 和 CLAUDE.md
2. 解析 plan.md 中的批注内容（`--批注：`）
3. 提炼新规则，去重后追加到 CLAUDE.md 约束总结
4. 基于 CLAUDE.md 规则重新生成 plan.md
5. 移除所有批注内容
6. 输出变更摘要

**输出格式**:
```
📝 文档更新完成
═══════════════════════════════════
更新时间: 2026-03-20

✅ CLAUDE.md 更新
━━━━━━━━━━━━━━━━━━━━━━━━━━
新增规则: 4 条
更新约束: 代码注释、时间处理、数据转换、职责下沉

✅ plan.md 更新
━━━━━━━━━━━━━━━━━━━━━━━━━━
移除批注: 8 处
修改章节: 4 个
新增内容: date_utils.py、数据模型方法

📊 变更摘要
━━━━━━━━━━━━━━━━━━━━━━━━━━
• 新增 lib/common/date_utils.py - 时间工具类
• 新增 EvaluationResult 方法：get_violation_count()、get_violation_summary()
• API 密钥优先级：环境变量 > 配置文件（移除向后兼容注释）
• 移除 Claude 配置文件依赖

📋 新增规则清单（已写入 CLAUDE.md）
━━━━━━━━━━━━━━━━━━━━━━━━━━
8. 代码注释：代码自注释，不写冗余注释，不体现演进过程
9. 时间处理：使用 lib/common/date_utils，不通过日志获取 timestamp
10. 数据转换：避免不必要的类型转换，优先使用原始数据
11. 职责下沉：计算逻辑下沉到数据对象
12. 参数精简：避免冗余参数，优先使用数据中已有的元数据
13. 函数命名：模块前缀 + 功能动词（如 execute_check）
14. 代码紧凑：移除不必要空行，代码结构紧凑
15. Logger 处理：保持现状，函数内部获取 logger，显式优于隐式
```

---

### 2. `/fix-plan update-claude` - 仅更新 CLAUDE.md

仅从批注中提炼规则更新 CLAUDE.md，不修改 plan.md。

**用法**:
```bash
/fix-plan update-claude
```

---

### 3. `/fix-plan review [file]` - 查看文档内容

查看 plan.md 或 CLAUDE.md 的当前内容。

**用法**:
```bash
/fix-plan review plan      # 查看 plan.md
/fix-plan review claude    # 查看 CLAUDE.md
```

---

### 4. `/fix-plan rules` - 查看规则清单

显示 CLAUDE.md 中当前的所有约束规则。

**用法**:
```bash
/fix-plan rules
```

**输出格式**:
```
📋 CLAUDE.md 约束规则清单
═══════════════════════════════════
最后更新: 2026-03-21

1. 命名规范
   • 函数名使用业务语义、动名词组合、见名知意

2. 面向对象
   • 隐藏实现细节、单一职责、使用对象方法

3. API 设计
   • 复杂留给自己、简单留给用户

4. 异常处理
   • 具体异常类、归档到对应模块

5. 数据模型
   • 不可变性、包含元数据、避免不必要转换、避免深层嵌套

6. 模块组织
   • 不新增 service 包、复用现有 lib/ 结构、通用模块归档到 lib/common

7. 测试要求
   • 测试未通过不允许提交代码

8. 代码注释
   • 代码自注释，不写冗余注释

9. 时间处理
   • 使用 lib/common/date_utils

10. 数据转换
    • 避免不必要的类型转换

11. 职责下沉
    • 计算逻辑下沉到数据对象

12. 参数精简
    • 避免冗余参数，使用数据中已有的元数据

13. 函数命名
    • 模块前缀 + 功能动词

14. 代码紧凑
    • 移除不必要空行

15. Logger 处理
    • 函数内部获取，显式优于隐式
   • 代码自注释，不写冗余注释，移除向后兼容代码

9. 时间处理
   • 使用 lib/common/date_utils，不通过日志获取 timestamp

10. 数据转换
    • 避免不必要的类型转换，优先使用原始数据结构

11. 职责下沉
    • 计算逻辑下沉到数据对象（result.get_summary()）
```

---

## 规则提取逻辑

批注 → 规则转换示例：

| 批注内容 | 提取的规则 |
|---------|-----------|
| "代码自注释可不写注释" | 代码自注释，不写冗余注释 |
| "移除向后兼容，不体现演进过程" | 移除向后兼容代码，不体现演进过程 |
| "建议抽取 date_utils 工具类" | 时间处理使用 lib/common/date_utils |
| "建议下沉至 result，隐藏实现细节" | 计算逻辑下沉到数据对象 |
| "为什么用转换，有更简洁的设计吗" | 避免不必要的类型转换 |

---

## 相关文件

- `plan.md` - 修复方案文档
- `CLAUDE.md` - 项目编码规范
- `research.md` - 问题研究报告
