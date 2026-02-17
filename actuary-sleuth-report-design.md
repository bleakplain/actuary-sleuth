# Actuary Sleuth 报告生成设计

## 一、顶层设计原则

### 1.1 核心原则

| 原则 | 说明 | 示例 |
|------|------|------|
| **动态生成** | 所有内容基于实际审核结果 | 无违规则不显示违规表格 |
| **结论先行** | 审核结论放在最前面 | 一、审核结论 |
| **问题导向** | 有问题才展示对应章节 | 无定价问题则省略定价分析 |
| **依据明确** | 每个问题都有法规依据 | 违规描述+法规条款+整改建议 |

### 1.2 报告结构（动态）

```
保险产品精算审核报告
├── 产品基本信息
│
├── 一、审核结论（始终显示）
│   ├── 审核意见（不推荐/条件推荐/需补充材料/推荐）
│   ├── 核心问题摘要（1-2句话）
│   └── 关键指标汇总表
│
├── 二、问题详情（有问题时显示）
│   ├── 审核依据（动态生成）
│   ├── 违规统计表
│   ├── 严重违规明细（如有）
│   ├── 中等违规明细（如有）
│   └── 定价问题分析（如有）
│
├── 三、修改建议（有问题时显示）
│   ├── P0级整改事项（如有严重违规）
│   └── P1级整改事项（如有中等违规）
│
└── 四、报告信息（始终显示）
    ├── 报告编号/生成时间
    └── 免责声明
```

---

## 二、动态生成逻辑

### 2.1 审核结论生成

```python
def generate_conclusion(score, summary, product_info):
    """生成审核结论"""

    high_count = summary['violation_severity']['high']
    medium_count = summary['violation_severity']['medium']
    total = summary['total_violations']

    # 审核意见决策树
    if high_count > 0:
        opinion = "不推荐上会"
        explanation = f"存在{high_count}项严重违规，触及监管红线"
    elif score >= 90:
        opinion = "推荐通过"
        explanation = "产品符合所有监管要求"
    elif score >= 75:
        opinion = "条件推荐"
        explanation = f"存在{medium_count}项中等问题，建议整改后提交"
    elif score >= 60:
        opinion = "需补充材料"
        explanation = f"存在{total}项问题，需补充说明材料"
    else:
        opinion = "不予推荐"
        explanation = "产品合规性不足"

    return {
        'opinion': opinion,
        'explanation': explanation,
        'highlights': generate_highlights(summary)
    }
```

### 2.2 问题详情生成

```python
def generate_details(violations, pricing_analysis, product_info):
    """生成问题详情"""

    details = {
        'has_issues': len(violations) > 0 or has_pricing_issues(pricing_analysis),
        'basis': generate_regulation_basis(violations, product_info),
        'violations': group_by_severity(violations),
        'pricing': extract_pricing_issues(pricing_analysis)
    }

    return details
```

### 2.3 审核依据生成

```python
def generate_regulation_basis(violations, product_info):
    """动态生成审核依据"""

    # 基于产品类型确定基础法规
    base_regulations = get_base_regulations(product_info['product_type'])

    # 基于违规点提取相关法规
    related_regulations = extract_related_regulations(violations)

    # 合并去重
    return merge_and_dedup(base_regulations, related_regulations)

def get_base_regulations(product_type):
    """根据产品类型获取基础法规"""

    regulation_map = {
        '寿险': ['保险法', '人身保险管理规定', '普通型人身保险管理办法'],
        '健康险': ['保险法', '健康保险管理办法'],
        '意外险': ['保险法', '意外伤害保险管理办法'],
        '万能险': ['保险法', '万能型人身保险管理办法'],
    }

    return regulation_map.get(product_type, ['保险法'])
```

---

## 三、报告模板设计

### 3.1 无问题报告模板

```markdown
# 保险产品精算审核报告

产品名称：XX终身寿险
保险公司：XX人寿保险股份有限公司
审核日期：2026年02月17日

## 一、审核结论

**审核意见**：推荐通过

**说明**：产品符合所有监管要求，未发现违规问题。

| 指标项 | 结果 |
|--------|------|
| 综合评分 | 95分 |
| 合规评级 | 优秀 |
| 违规总数 | 0项 |
| 定价评估 | 合理 |

## 四、报告信息

报告编号：RPT-20260217-143020
生成时间：2026年02月17日 14:30
审核系统：Actuary Sleuth v3.0

免责声明：本报告由AI精算审核系统生成...
```

### 3.2 有问题报告模板

```markdown
# 保险产品精算审核报告

## 一、审核结论

**审核意见**：不推荐上会

**说明**：存在2项严重违规，触及监管红线，需完成整改后重新审核。

## 二、问题详情及依据

**审核依据**：
- 《中华人民共和国保险法》第十七条
- 《人身保险公司保险条款和保险费率管理办法》第X条

### 2.1 违规统计

| 级别 | 数量 | 占比 |
|------|------|------|
| 严重 | 2项 | 20% |
| 中等 | 5项 | 50% |
| 轻微 | 3项 | 30% |

### 2.2 严重违规明细

| 规则 | 违规描述 | 涉及条款 | 法规依据 | 整改建议 |
|------|----------|----------|----------|----------|
| N001 | 包含保证收益表述 | 第6条 | 保险法第十七条 | 改为演示收益 |

## 三、修改建议

### 3.1 P0级整改事项（必须立即整改）

1. 删除第6条中"保证收益"相关表述
2. 补充第15条犹豫期起算日期

## 四、报告信息
...
```

---

## 四、实现要点

### 4.1 数据流向

```
violations (违规列表)
    ↓
group_by_severity() → 按严重程度分组
    ↓
extract_regulations() → 提取相关法规
    ↓
format_tables() → 格式化表格
    ↓
generate_content() → 生成报告内容
```

### 4.2 关键函数

| 函数 | 输入 | 输出 |
|------|------|------|
| `generate_conclusion()` | score, summary | 审核意见+说明 |
| `generate_regulation_basis()` | violations, product_type | 法规依据列表 |
| `format_violation_table()` | violations | Markdown表格 |
| `create_report()` | 全部数据 | 完整报告 |

### 4.3 条件渲染

```python
# 只在有问题时显示
if high_violations:
    render_high_violation_table(high_violations)

if medium_violations:
    render_medium_violation_table(medium_violations)

if pricing_issues:
    render_pricing_analysis(pricing_issues)
```

---

## 五、质量标准

### 5.1 报告质量检查清单

- [ ] 审核结论与数据一致
- [ ] 有问题才显示问题章节
- [ ] 每个违规都有对应法规依据
- [ ] 整改建议可操作
- [ ] 表格数据准确
- [ ] 报告编号唯一
- [ ] 免责声明完整

### 5.2 输出规范

| 项目 | 规范 |
|------|------|
| 报告编号 | RPT-YYYYMMDD-HHMMSS |
| 评分范围 | 0-100 |
| 评级 | 优秀/良好/合格/不合格 |
| 违规级别 | high/medium/low |
| 法规引用 | 法规名称+条款号 |
