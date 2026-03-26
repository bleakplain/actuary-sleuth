# 全流程测试计划 - 真实飞书保险产品文档审核

## 测试目标

基于真实飞书在线文档 `https://hcnhqpzu5f0a.feishu.cn/docx/Lg5tdB2MKoymm0xM5nRcaJxTn3d` 完成从文档预处理、审核到报告生成的全流程测试。

## 测试文档信息

- **文档URL**: https://hcnhqpzu5f0a.feishu.cn/docx/Lg5tdB2MKoymm0xM5nRcaJxTn3d
- **文档类型**: 保险产品条款文档
- **测试范围**: 完整的审核流程（预处理 → 负面清单检查 → 定价分析 → 结果计算 → 报告生成）

---

## 测试阶段

### 阶段1: 文档获取与预处理 (Document Fetching & Preprocessing)

#### 1.1 文档获取测试
**文件**: `tests/integration/test_real_feishu_workflow.py`

**测试用例**:
```python
class TestDocumentFetching:
    def test_fetch_real_feishu_document(self):
        """测试从真实飞书URL获取文档内容"""
        from lib.preprocessing.document_fetcher import fetch_feishu_document

        url = "https://hcnhqpzu5f0a.feishu.cn/docx/Lg5tdB2MKoymm0xM5nRcaJxTn3d"
        content = fetch_feishu_document(url)

        assert content is not None
        assert len(content) > 1000  # 文档应该有足够的内容
        assert "保险" in content or "产品" in content  # 验证是保险产品文档
```

**验证点**:
- [ ] 飞书文档能够成功获取
- [ ] 返回的内容不为空
- [ ] 内容格式正确（UTF-8编码）
- [ ] 包含预期的保险产品关键词

#### 1.2 文档预处理测试
**测试用例**:
```python
class TestDocumentPreprocessing:
    def test_preprocess_real_document(self):
        """测试真实文档的预处理流程"""
        from lib.preprocessing import DocumentExtractor
        from lib.llm import LLMClientFactory

        # 获取文档内容
        url = "https://hcnhqpzu5f0a.feishu.cn/docx/Lg5tdB2MKoymm0xM5nRcaJxTn3d"
        content = fetch_feishu_document(url)

        # 执行预处理
        llm_client = LLMClientFactory.get_doc_preprocess_llm()
        extractor = DocumentExtractor(llm_client)

        result = extractor.extract(
            document=content,
            source_type='text'
        )

        assert result.success is True
        assert result.get_product_info() is not None
        assert len(result.get_clauses()) > 0
```

**验证点**:
- [ ] 预处理成功完成
- [ ] 产品信息正确提取（产品名称、公司、类别、保险期间等）
- [ ] 条款信息正确提取（至少包含3条条款）
- [ ] 费率信息正确提取（如有费率表）

#### 1.3 产品分类验证
**测试用例**:
```python
def test_product_classification():
    """验证产品分类结果"""
    from lib.common.models import ProductCategory

    # 获取预处理结果
    product = preprocessed_result.product

    # 验证产品分类
    assert product.category in ProductCategory._value2member_map_

    # 验证必填字段
    assert product.name is not None
    assert product.company is not None
    assert product.period is not None
```

---

### 阶段2: 负面清单检查 (Negative List Check)

#### 2.1 条款违规检查
**测试用例**:
```python
class TestNegativeListCheck:
    def test_check_real_clauses(self):
        """测试真实条款的负面清单检查"""
        import check

        clauses = preprocessed_result.clauses

        result = check.execute({'clauses': clauses})

        assert result.success is True
        assert isinstance(result.get_violations(), list)

        # 验证违规信息格式
        for violation in result.get_violations():
            assert 'clause' in violation
            assert 'regulation' in violation
            assert 'reason' in violation
```

**验证点**:
- [ ] 负面清单检查成功执行
- [ ] 返回违规列表（可能为空）
- [ ] 违规信息包含：条款内容、相关法规、违规原因
- [ ] 违规严重程度正确分类（P1/P2/P3）

#### 2.2 违规统计验证
**测试用例**:
```python
def test_violation_statistics():
    """统计违规情况"""
    violations = checked_result.violations

    # 按严重程度统计
    p1_count = sum(1 for v in violations if v.get('severity') == 'P1')
    p2_count = sum(1 for v in violations if v.get('severity') == 'P2')
    p3_count = sum(1 for v in violations if v.get('severity') == 'P3')

    print(f"P1违规: {p1_count}, P2违规: {p2_count}, P3违规: {p3_count}")
```

---

### 阶段3: 定价分析 (Pricing Analysis)

#### 3.1 定价参数分析
**测试用例**:
```python
class TestPricingAnalysis:
    def test_analyze_real_pricing(self):
        """测试真实产品的定价分析"""
        import scoring
        from lib.common.product import map_to_scoring_type

        pricing_params = preprocessed_result.pricing_params
        category = preprocessed_result.product.category
        scoring_type = map_to_scoring_type(category)

        result = scoring.execute({
            'pricing_params': pricing_params,
            'scoring_type': scoring_type
        })

        assert result.success is True
        assert result.get_pricing() is not None
```

**验证点**:
- [ ] 定价分析成功执行
- [ ] 返回定价分析结果
- [ ] 包含风险评估信息
- [ ] 包含定价合理性判断

#### 3.2 分析结果验证
**测试用例**:
```python
def test_pricing_analysis_validation():
    """验证定价分析结果"""
    pricing = analyzed_result.pricing_analysis

    # 验证分析字段
    assert 'risk_assessment' in pricing or 'analysis' in pricing
    assert 'score' in pricing or 'rating' in pricing
```

---

### 阶段4: 结果计算 (Result Calculation)

#### 4.1 审核结果计算
**测试用例**:
```python
class TestResultCalculation:
    def test_calculate_audit_result(self):
        """测试审核结果计算"""
        from lib.audit.evaluation import calculate_result

        result = calculate_result(analyzed_result)

        assert result is not None
        assert hasattr(result, 'score')
        assert hasattr(result, 'get_violations')
        assert hasattr(result, 'to_dict')
```

**验证点**:
- [ ] 结果计算成功
- [ ] 分数在0-100范围内
- [ ] 包含违规摘要信息
- [ ] 包含整体评估（通过/有条件通过/不通过）

#### 4.2 结果格式验证
**测试用例**:
```python
def test_result_format():
    """验证结果格式"""
    result_dict = result.to_dict()

    # 验证必需字段
    assert 'score' in result_dict
    assert 'overall_assessment' in result_dict
    assert 'violations' in result_dict
    assert 'summary' in result_dict
```

---

### 阶段5: 数据库持久化 (Database Persistence)

#### 5.1 审核记录保存
**测试用例**:
```python
class TestDatabasePersistence:
    def test_save_audit_record(self):
        """测试审核记录保存到数据库"""
        from lib.common.database import save_audit_record
        from lib.common.id_generator import IDGenerator

        audit_id = IDGenerator.generate_audit()
        document_url = "https://hcnhqpzu5f0a.feishu.cn/docx/Lg5tdB2MKoymm0xM5nRcaJxTn3d"

        save_success = save_audit_record(
            audit_id=audit_id,
            document_url=document_url,
            violations=result.get_violations(),
            score=result.score
        )

        assert save_success is True
```

**验证点**:
- [ ] 审核记录成功保存到SQLite数据库
- [ ] audit_id正确生成和保存
- [ ] 违规信息正确序列化
- [ ] 分数正确保存

#### 5.2 数据查询验证
**测试用例**:
```python
def test_query_audit_record():
    """验证审核记录可以正确查询"""
    from lib.common.database import get_audit_record

    record = get_audit_record(audit_id)

    assert record is not None
    assert record['audit_id'] == audit_id
    assert record['document_url'] == document_url
```

---

### 阶段6: 报告生成 (Report Generation)

#### 6.1 报告生成测试
**测试用例**:
```python
class TestReportGeneration:
    def test_generate_audit_report(self):
        """测试审核报告生成"""
        from lib.reporting import ReportGenerationTemplate
        from lib.reporting.model import EvaluationContext
        from lib.audit.evaluation import calculate_result

        # 计算审核结果
        audit_result = calculate_result(analyzed_result)

        # 构建评估上下文
        context = EvaluationContext(
            product=preprocessed_result.product,
            clauses=preprocessed_result.clauses,
            violations=checked_result.violations,
            pricing=analyzed_result.pricing_analysis,
            audit_result=audit_result
        )

        # 生成报告
        template = ReportGenerationTemplate()
        report = template.generate(context)

        assert report is not None
        assert 'content' in report or 'blocks' in report
```

**验证点**:
- [ ] 报告成功生成
- [ ] 报告包含产品基本信息
- [ ] 报告包含审核结果
- [ ] 报告包含违规详情
- [ ] 报告包含整改建议（如有违规）

#### 6.2 报告导出测试
**测试用例**:
```python
def test_export_report_to_docx():
    """测试报告导出为DOCX格式"""
    from lib.reporting import export_docx
    import tempfile
    from pathlib import Path

    # 生成报告数据
    report_data = generate_report_data()

    # 导出到DOCX
    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as f:
        output_path = Path(f.name)

    try:
        export_docx(report_data, str(output_path))

        assert output_path.exists()
        assert output_path.stat().st_size > 0
    finally:
        if output_path.exists():
            output_path.unlink()
```

**验证点**:
- [ ] DOCX文件成功生成
- [ ] 文件大小合理（不是空文件）
- [ ] 文件可以正常打开

---

## 测试文件结构

```
tests/integration/test_real_feishu_workflow.py
├── TestDocumentFetching
│   ├── test_fetch_real_feishu_document
│   └── test_document_content_validation
├── TestDocumentPreprocessing
│   ├── test_preprocess_real_document
│   ├── test_product_info_extraction
│   └── test_clauses_extraction
├── TestNegativeListCheck
│   ├── test_check_real_clauses
│   └── test_violation_statistics
├── TestPricingAnalysis
│   ├── test_analyze_real_pricing
│   └── test_pricing_analysis_validation
├── TestResultCalculation
│   ├── test_calculate_audit_result
│   └── test_result_format
├── TestDatabasePersistence
│   ├── test_save_audit_record
│   └── test_query_audit_record
├── TestReportGeneration
│   ├── test_generate_audit_report
│   └── test_export_report_to_docx
└── TestFullWorkflow
    ├── test_end_to_end_workflow
    └── test_workflow_performance
```

---

## 测试依赖

### 环境变量
需要在 `.env` 文件中配置：
```bash
# 飞书API配置
FEISHU_APP_ID=cli_a900c2ed51335ccd
FEISHU_APP_SECRET=xU3udM9Wax1HFwCXFdwwdgXPH0xjb1TT
FEISHU_TARGET_GROUP_ID=oc_d7b83e1f9eb58c6797b061dcc33d212f

# 智谱AI配置（用于LLM）
ZHIPU_API_KEY=7d0a2b4545c94ca088f4d869a9e2cbbd.oRxlgkhqRF1rbjNp

# 调试模式（可选）
DEBUG=false
```

### Python依赖
- `pytest`: 测试框架
- `python-docx`: DOCX文件操作
- `llama-index-core`: RAG引擎（可选）
- `lancedb`: 向量数据库（可选）

---

## 测试执行顺序

### 单阶段测试
可以独立运行每个阶段的测试：
```bash
# 仅测试文档获取
pytest tests/integration/test_real_feishu_workflow.py::TestDocumentFetching -v

# 仅测试预处理
pytest tests/integration/test_real_feishu_workflow.py::TestDocumentPreprocessing -v

# 仅测试负面清单检查
pytest tests/integration/test_real_feishu_workflow.py::TestNegativeListCheck -v
```

### 全流程测试
```bash
# 运行完整工作流程测试
pytest tests/integration/test_real_feishu_workflow.py::TestFullWorkflow -v
```

---

## 预期结果

### 成功标准
1. ✅ 文档成功从飞书获取
2. ✅ 预处理提取出完整的产品信息和条款
3. ✅ 负面清单检查完成，返回违规列表
4. ✅ 定价分析完成，返回风险评估
5. ✅ 结果计算完成，生成审核结果和分数
6. ✅ 审核记录成功保存到数据库
7. ✅ 审核报告成功生成
8. ✅ 报告成功导出为DOCX文件

### 失败处理
每个阶段都应该有适当的错误处理：
- 网络错误：飞书API调用失败
- 格式错误：文档格式不符合预期
- LLM错误：AI服务调用失败
- 数据库错误：保存失败

---

## 测试清理

### 临时文件清理
```python
@pytest.fixture(autouse=True)
def cleanup_test_data():
    """自动清理测试数据"""
    # 测试前清理
    yield
    # 测试后清理
    # 删除临时生成的文件
    # 清理测试数据库记录
```

---

## 性能基准

### 预期执行时间
- 文档获取: < 5秒
- 预处理: < 30秒
- 负面清单检查: < 10秒
- 定价分析: < 20秒
- 结果计算: < 5秒
- 报告生成: < 10秒
- **总计**: < 80秒

---

## 风险与限制

### 已知风险
1. **网络依赖**: 依赖飞书API的可用性
2. **LLM依赖**: 依赖智谱AI服务的可用性
3. **文档格式**: 文档格式可能不符合预期
4. **数据一致性**: 每次运行可能产生不同的LLM结果

### 限制
1. 测试需要真实的API密钥
2. 测试会产生实际的数据库记录
3. 测试可能消耗LLM配额

---

## 后续改进

1. **测试隔离**: 使用测试数据库，避免污染生产数据
2. **Mock回退**: 在无法访问真实服务时使用Mock
3. **并行测试**: 支持多个文档并行测试
4. **结果对比**: 保存测试结果基线，用于回归测试
5. **CI/CD集成**: 将测试集成到持续集成流程
