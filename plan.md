# Actuary Sleuth 重构计划

## 概述

本文档记录 Actuary Sleuth 项目的重构方案和实施进度。

**重构原则**：遵循 Python 编码规范、清晰模块职责、最小化改动。

---

## ✅ 已完成

### 第一阶段

#### 1. API 密钥优先级调整
- 修改 `scripts/lib/config.py`
- 优先级：环境变量 `ZHIPU_API_KEY` > 配置文件
- 移除 Claude 配置文件依赖

#### 2. 模块职责边界重构
- 新建 `scripts/lib/common/date_utils.py` - 时间工具类
- 新建 `scripts/lib/common/exceptions.py` - 通用异常类
- 新建 `scripts/lib/preprocessing/exceptions.py` - 预处理异常类
- 新建 `scripts/lib/preprocessing/document_fetcher.py` - 文档获取模块
- 重构 `scripts/audit.py` - 流程编排，精简 730+ 行
- 修改 `scripts/lib/common/database.py` - 使用具体异常类
- 修改 `scripts/lib/common/audit.py` - 增强数据模型方法

#### 3. 数据模型方法增强
为 `EvaluationResult` 添加方法：
- `get_violations()`, `get_violation_count()`, `get_violation_summary()`, `to_dict()`

**测试结果**：121 passed, 5 skipped

### 第二阶段

#### 4. 数据模型扁平化 ✅
为数据对象添加快捷属性，消除深层嵌套：
- `CheckedResult.audit_id`, `.product`, `.clauses`
- `AnalyzedResult.audit_id`, `.product`, `.preprocessed`, `.violations`
- `EvaluationResult.audit_id`, `.product`, `.violations`

访问路径简化：
- `checked.preprocessed.product.category` → `checked.product.category`
- `analyzed.checked.preprocessed.audit_id` → `analyzed.audit_id`

#### 5. 统一 Result 类 ✅
- 新建 `lib/common/result.py` - 统一的 ProcessResult 类
- 工厂方法：`success_result()`, `error_result()`
- 转换方法：`from_dict()`, `to_dict()`
- 访问方法：`get()`, `get_or_raise()`

---

## 🔄 待重构

### 重构方案：preprocess 模块拆分

**问题描述**：

`preprocess.py` 包含多个职责：
- 文档提取
- 规范化
- 产品类型分类
- 结果验证

**解决方案**：

拆分为独立模块：
- `lib/preprocessing/extractor.py` - 提取逻辑
- `lib/preprocessing/normalizer.py` - 规范化逻辑
- `lib/preprocessing/validator.py` - 验证逻辑
- `lib/preprocessing/classifier.py` - 分类逻辑
- `lib/preprocessing/orchestrator.py` - 流程编排

**影响文件**：
- 新建多个模块文件
- 修改 `scripts/preprocess.py`
- 更新测试

---

## 后续优化建议

1. **缓存机制**：使用 `functools.lru_cache` 或 Redis
2. **大文件优化**：实现流式处理
3. **法规版本管理**：添加 version 字段
4. **测试覆盖**：提高到 80% 以上
