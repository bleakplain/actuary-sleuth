# Changelog

All notable changes to Actuary Sleuth will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-02-27

### Added
- **Word 文档导出功能**
  - 基于 docx-js 生成标准 Word 文档，完美支持中文
  - 支持专业格式：标题、表格、样式等
  - 可配置输出目录、验证选项、超时设置
  - `DocxExporter` 类提供完整的导出接口
  - `export_docx()` 便捷函数
- **飞书推送集成**
  - 通过 OpenClaw 自动推送生成的报告到指定群组
  - `_FeishuPusher` 类处理推送逻辑
  - 支持文档和文本消息推送
- **结果封装类**
  - `ExportResult` - 通用导出结果
  - `GenerationResult` - 文档生成结果
  - `PushResult` - 推送结果
  - 统一的错误处理和类型安全
- **输入验证模块**
  - `validate_evaluation_context()` - 验证评估上下文
  - `validate_title()` - 验证文档标题
  - `validate_file_path()` - 验证文件路径
- **常量管理**
  - `DocxConstants` - Docx 相关常量集合
  - `DocxUnits` - 单位常量（DXA、字号等）
  - `DocxPage` - 页面常量（尺寸、边距）
  - `DocxSpacing` - 间距常量
  - `DocxTable` - 表格常量
  - `DocxStyle` - 样式常量
- **配置管理**
  - `OpenClawConfig` - OpenClaw 配置类
  - 可配置的超时设置
  - 飞书目标群组 ID 配置

### Changed
- **报告生成模块重构**
  - 使用模板方法模式和策略模式
  - 引入 `EvaluationContext` 数据模型
  - `_InsuranceProduct` 改为内部类
- **异常体系改进**
  - 添加 `ExportException` 导出异常
  - 特定异常类型用于更好的错误处理
  - 添加堆栈跟踪日志
- **代码优化**
  - 提取辅助方法减少代码重复
  - 改进错误消息的可读性
  - 添加依赖注入支持提高可测试性
  - 使用 TYPE_CHECKING 解决循环导入

### Fixed
- 修复 Word 文档中文乱码问题（使用 docx-js 替代 python-docx）
- 修复 f-string 嵌套导致的 JavaScript 语法错误
- 修复 Node.js 模块查找问题（设置 NODE_PATH）
- 修复重复的列宽计算
- 修复临时文件未在失败时清理的问题

### Technical Details
- **docx_generator.py** - 6 个辅助方法，可配置超时，常量提取
- **feishu_pusher.py** - 命令提取，错误解析，regex 验证
- **docx_exporter.py** - 依赖注入，特定异常处理，类型提示

## [2.0.0] - 2024-XX-XX

### Added
- 向量检索功能
  - 基于 LanceDB 的语义搜索
  - 支持 Ollama 本地嵌入模型
- 飞书文档导出
  - 支持导出为飞书在线文档
- 配置管理系统
  - 统一的配置接口
  - 支持环境变量覆盖

## [1.0.0] - 2024-XX-XX

### Added
- 初始版本
- 基础审核功能
  - 负面清单检查
  - 定价合理性分析
  - 文档预处理
  - 审核报告生成

---

## 版本说明

- **[X.Y.Z]** - 正式发布版本
  - X - 主版本号（不兼容的 API 变更）
  - Y - 次版本号（向下兼容的功能新增）
  - Z - 修订号（向下兼容的问题修复）
