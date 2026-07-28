from api.routers.compliance import _apply_requested_product_name, _resolve_retrieval_context
from lib.common.product_tags import ProductLine, ProductSubtype, ProductTags
from lib.doc_parser.models import AuditDocument
from lib.doc_parser.pd.product_tagging import build_product_tags


def test_requested_product_name_replaces_recognized_name_and_tags():
    audit_doc = AuditDocument(
        file_name="upload.docx",
        file_type=".docx",
        product_name="旧定期寿险条款",
        product_tags=build_product_tags("旧定期寿险条款"),
    )

    result = _apply_requested_product_name(
        audit_doc,
        "某某附加团体医疗保险条款",
        "本合同不保证续保。",
    )

    assert result.product_name == "某某附加团体医疗保险条款"
    assert result.product_tags.line is ProductLine.HEALTH
    assert result.product_tags.renewal_type.value == "non_guaranteed"
    assert result.is_rider is True
    assert result.group_or_individual == "团体"


def test_retrieval_context_recovers_category():
    category, warnings = _resolve_retrieval_context(
        None,
        ProductTags(line=ProductLine.HEALTH, primary_subtype=ProductSubtype.MEDICAL),
    )

    assert category == "医疗险"
    assert len(warnings) == 1
    assert "产品标签" in warnings[0]
