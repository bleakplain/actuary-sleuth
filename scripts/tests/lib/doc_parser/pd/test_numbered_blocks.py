from lib.doc_parser.models import AuditBlockType, AuditDocument, DataTable, TableType
from lib.doc_parser.pd.numbered_blocks import (
    SourceRecord,
    SourceRecordKind,
    assemble_numbered_content,
    is_numbering_table_rows,
    normalize_clause_number,
)


def _row(
    order: int,
    *fields: str,
    numbering_stream: bool = True,
) -> SourceRecord:
    return SourceRecord(
        order=order,
        kind=SourceRecordKind.TABLE_ROW,
        fields=tuple(fields),
        table_index=0,
        row_index=order,
        numbering_stream=numbering_stream,
    )


def test_number_normalization_does_not_split_internal_list_markers():
    assert normalize_clause_number("2．5．4") == ("2.5.4", (2, 5, 4))
    assert normalize_clause_number("1.") == ("1", (1,))
    assert normalize_clause_number("0.8") is None
    assert normalize_clause_number("1）") is None
    assert normalize_clause_number("（一）") is None
    assert normalize_clause_number("第2.5.4条") is None


def test_decimal_value_rows_are_not_numbering_stream_but_three_levels_are():
    assert not is_numbering_table_rows((
        ("费率", "保险金额"),
        ("1.5", "100000"),
        ("0.8", "200000"),
    ))
    assert is_numbering_table_rows((
        ("2.5.4", "医疗费用保险金"),
        ("", "本条责任正文"),
    ))

    content = assemble_numbered_content((
        SourceRecord(
            0,
            SourceRecordKind.TABLE_ROW,
            fields=("1.5", "100000"),
        ),
        SourceRecord(
            1,
            SourceRecordKind.TABLE_ROW,
            fields=("0.8", "200000"),
        ),
        _row(2, "2.5.4", "医疗费用保险金\n责任正文"),
    ))
    assert [clause.number for clause in content.clauses] == ["2.5.4"]
    assert "1.5\n100000" in content.unclassified_sections[0].content
    assert "0.8\n200000" in content.unclassified_sections[0].content
    assert content.coverage_attestation.coverage_attested


def test_inline_decimal_amounts_are_content_but_real_decimal_clause_survives():
    content = assemble_numbered_content((
        SourceRecord(
            0,
            SourceRecordKind.TEXT,
            fields=("医疗费用按以下档次给付",),
        ),
        SourceRecord(
            1,
            SourceRecordKind.TEXT,
            fields=("1.5 万元以下按100%给付",),
        ),
        SourceRecord(
            2,
            SourceRecordKind.TEXT,
            fields=("2.0 万元以上按80%给付",),
        ),
        SourceRecord(
            3,
            SourceRecordKind.TEXT,
            fields=("3.5 年以下按短期费率计算",),
        ),
        SourceRecord(
            4,
            SourceRecordKind.TEXT,
            fields=("1.5 保证续保",),
        ),
        SourceRecord(
            5,
            SourceRecordKind.TEXT,
            fields=("保证续保期间为6年。",),
        ),
        SourceRecord(
            6,
            SourceRecordKind.TEXT,
            fields=("1.6 年金领取",),
        ),
        SourceRecord(
            7,
            SourceRecordKind.TEXT,
            fields=("年金领取方式由投保人约定。",),
        ),
    ))

    assert [clause.number for clause in content.clauses] == ["1.5", "1.6"]
    assert content.clauses[0].title == "保证续保"
    assert content.clauses[0].text == "保证续保期间为6年。"
    assert content.clauses[1].title == "年金领取"
    assert content.clauses[1].text == "年金领取方式由投保人约定。"
    assert content.unclassified_sections[0].content == (
        "医疗费用按以下档次给付\n"
        "1.5 万元以下按100%给付\n"
        "2.0 万元以上按80%给付\n"
        "3.5 年以下按短期费率计算"
    )
    assert content.coverage_attestation.coverage_attested


def test_confirmed_numbering_stream_keeps_unit_named_definition_clause():
    content = assemble_numbered_content((
        _row(0, "7", "名词释义"),
        _row(1, "7.1", "周岁\n以身份证记载的出生日期为基础计算。"),
    ))

    assert [clause.number for clause in content.clauses] == ["7", "7.1"]
    assert content.clauses[1].title == "周岁"
    assert "出生日期" in content.clauses[1].text
    assert content.coverage_attestation.coverage_attested


def test_plain_text_monotonic_root_sequence_defines_clause_boundaries():
    content = assemble_numbered_content((
        SourceRecord(
            0, SourceRecordKind.TEXT, fields=("1 总则",),
        ),
        SourceRecord(
            1, SourceRecordKind.TEXT, fields=("2 保险责任",),
        ),
        SourceRecord(
            2, SourceRecordKind.TEXT, fields=("3 责任免除",),
        ),
    ))

    assert [clause.number for clause in content.clauses] == ["1", "2", "3"]
    assert [clause.title for clause in content.clauses] == [
        "总则", "保险责任", "责任免除",
    ]
    assert all(not clause.text for clause in content.clauses)
    assert content.coverage_attestation.coverage_attested


def test_root_measurements_and_inline_body_list_do_not_define_clauses():
    content = assemble_numbered_content((
        SourceRecord(
            0, SourceRecordKind.TEXT, fields=("给付档次如下：",),
        ),
        SourceRecord(
            1, SourceRecordKind.TEXT, fields=("1 100万元",),
        ),
        SourceRecord(
            2, SourceRecordKind.TEXT, fields=("2 1,000元",),
        ),
        SourceRecord(
            3, SourceRecordKind.TEXT, fields=("3 30%",),
        ),
        SourceRecord(
            4, SourceRecordKind.TEXT, fields=("4 18周岁",),
        ),
        SourceRecord(
            5, SourceRecordKind.TEXT, fields=("保障责任清单：",),
        ),
        SourceRecord(
            6, SourceRecordKind.TEXT, fields=("1）住院医疗",),
        ),
        SourceRecord(
            7, SourceRecordKind.TEXT, fields=("2）门诊医疗",),
        ),
        SourceRecord(
            8, SourceRecordKind.TEXT, fields=("3）特定药品医疗",),
        ),
    ))

    assert content.clauses == ()
    assert content.coverage_attestation.coverage_attested
    unclassified = "\n".join(
        section.content for section in content.unclassified_sections
    )
    assert "1 100万元" in unclassified
    assert "2 1,000元" in unclassified
    assert "3 30%" in unclassified
    assert "4 18周岁" in unclassified
    assert "1）住院医疗" in unclassified


def test_plain_three_row_data_table_is_not_a_root_clause_sequence():
    content = assemble_numbered_content((
        _row(0, "1", "北京", "100万元", numbering_stream=False),
        _row(1, "2", "上海", "200万元", numbering_stream=False),
        _row(2, "3", "广州", "300万元", numbering_stream=False),
    ))

    assert content.clauses == ()
    assert content.coverage_attestation.coverage_attested
    assert "北京" in content.unclassified_sections[0].content
    assert "广州" in content.unclassified_sections[0].content


def test_blank_number_rows_continue_until_next_number_and_build_hierarchy():
    content = assemble_numbered_content((
        _row(0, "1", "保险责任"),
        _row(1, "1.1", "医疗费用保险金"),
        _row(2, "", "1）住院医疗费用保险金\n住院责任正文"),
        _row(3, "", "（一）特殊门诊\n门诊责任正文"),
        _row(4, "1.2", "责任免除\n免责正文"),
    ))

    assert [clause.number for clause in content.clauses] == [
        "1", "1.1", "1.2",
    ]
    medical = content.clauses[1]
    assert medical.parent_number == "1"
    assert medical.ancestor_numbers == ("1",)
    assert medical.hierarchy_path == "1 > 1.1"
    assert "1）住院医疗费用保险金" in medical.text
    assert "（一）特殊门诊" in medical.text
    assert "免责正文" not in medical.text
    assert content.clauses[0].container_only
    assert content.coverage_attestation.coverage_attested
    assert content.coverage_attestation.source_record_count == 5
    assert content.coverage_attestation.assigned_record_count == 5
    document = AuditDocument(
        file_name="层级.docx",
        file_type=".docx",
        clauses=content.clauses,
        coverage_attestation=content.coverage_attestation,
    )
    root_block = next(
        block for block in document.audit_blocks if block.number == "1"
    )
    assert root_block.container_only
    assert root_block.hierarchy_level == 1
    assert root_block.hierarchy_path == "1"


def test_coverage_attestation_fails_for_unassigned_or_duplicate_source_order():
    unassigned = assemble_numbered_content((
        _row(0, "1", "保险责任"),
        SourceRecord(1, SourceRecordKind.TEXT, fields=("",)),
    ))
    assert not unassigned.coverage_attestation.coverage_attested
    assert unassigned.coverage_attestation.unassigned_orders == (1,)

    duplicate = assemble_numbered_content((
        _row(0, "1", "保险责任"),
        _row(0, "1.1", "等待期\n等待期为30日"),
    ))
    assert not duplicate.coverage_attestation.coverage_attested
    assert duplicate.coverage_attestation.duplicate_source_orders == (0,)


def test_data_table_without_raw_text_is_fully_preserved_inside_clause():
    table = DataTable(
        data=[["项目", "限额"], ["医疗", "100万"]],
        table_type=TableType.COVERAGE,
        remark="保证续保期间为六年",
    )
    content = assemble_numbered_content((
        _row(0, "2.5.4", "医疗费用保险金"),
        SourceRecord(1, SourceRecordKind.DATA_TABLE, data_table=table),
    ))
    document = AuditDocument(
        file_name="表名.docx",
        file_type=".docx",
        clauses=content.clauses,
        coverage_attestation=content.coverage_attestation,
    )

    assert content.coverage_attestation.coverage_attested
    assert "保证续保期间为六年" in content.clauses[0].text
    assert "项目\t限额\n医疗\t100万" in content.clauses[0].text
    assert "保证续保期间为六年" in document.canonical_text


def test_data_table_coverage_checks_raw_text_and_cell_data_separately():
    table = DataTable(
        data=[["项目", "限额"], ["医疗", "200万"]],
        table_type=TableType.COVERAGE,
        raw_text="项目\t限额\n医疗\t100万",
        remark="保障计划表",
    )
    content = assemble_numbered_content((
        _row(0, "2.5.4", "医疗费用保险金"),
        SourceRecord(1, SourceRecordKind.DATA_TABLE, data_table=table),
    ))

    assert "保障计划表" in content.clauses[0].text
    assert "医疗\t100万" in content.clauses[0].text
    assert not content.coverage_attestation.coverage_attested
    assert content.coverage_attestation.truncated_orders == (1,)


def test_long_first_payload_line_keeps_all_following_lines():
    first_line = "这是一个超过二十五个汉字并且同时包含正文内容的条款标题 第一段正文"
    second_line = "第二段正文不得在标题拆分时丢失"
    content = assemble_numbered_content((
        _row(0, "2.5.4", f"{first_line}\n{second_line}"),
    ))

    clause = content.clauses[0]
    assert second_line in f"{clause.title}\n{clause.text}"
    assert content.coverage_attestation.coverage_attested
    assert content.coverage_attestation.truncated_orders == ()


def test_full_width_number_and_three_levels_have_prefix_parent():
    content = assemble_numbered_content((
        _row(0, "2", "保险责任及责任免除"),
        _row(1, "2．5", "保险责任"),
        _row(2, "2．5．4", "特定药品费用保险金\n第一段"),
        _row(3, "", "第二段"),
    ))

    clause = content.clauses[-1]
    assert clause.number == "2.5.4"
    assert clause.parent_number == "2.5"
    assert clause.ancestor_numbers == ("2", "2.5")
    assert clause.hierarchy_level == 3
    assert clause.text == "第一段\n第二段"


def test_cross_page_repeated_number_supplies_missing_title_without_data_loss():
    content = assemble_numbered_content((
        SourceRecord(
            0,
            SourceRecordKind.TABLE_ROW,
            fields=("2.5.4",),
            page_number=1,
            numbering_stream=True,
        ),
        SourceRecord(
            1,
            SourceRecordKind.TABLE_ROW,
            fields=("2.5.4", "医疗费用保险金", "第二页责任正文"),
            page_number=2,
            numbering_stream=True,
        ),
    ))

    assert len(content.clauses) == 1
    assert content.clauses[0].number == "2.5.4"
    assert content.clauses[0].title == "医疗费用保险金"
    assert content.clauses[0].text == "第二页责任正文"
    assert content.coverage_attestation.coverage_attested
    assert content.coverage_attestation.source_record_count == 2
    assert content.coverage_attestation.assigned_record_count == 2


def test_detected_section_heading_inside_clause_is_content_not_boundary():
    content = assemble_numbered_content((
        _row(0, "2.5.4", "医疗费用保险金\n责任正文"),
        SourceRecord(
            1,
            SourceRecordKind.TEXT,
            fields=("责任免除",),
        ),
        SourceRecord(
            2,
            SourceRecordKind.TEXT,
            fields=("被保险人的既往症不承担保险责任。",),
        ),
        _row(3, "2.5.5", "住院津贴保险金\n下一条正文"),
    ))

    assert [clause.number for clause in content.clauses] == [
        "2.5.4", "2.5.5",
    ]
    assert "责任免除" in content.clauses[0].text
    assert "被保险人的既往症不承担保险责任。" in content.clauses[0].text
    assert "下一条正文" not in content.clauses[0].text
    assert content.exclusions == ()
    assert content.coverage_attestation.coverage_attested


def test_numbered_note_text_attaches_to_referenced_clause_not_new_boundary():
    content = assemble_numbered_content((
        _row(0, "2", "保险责任"),
        _row(1, "2.1", "医疗保险金\n正文第一段"),
        SourceRecord(
            2,
            SourceRecordKind.AUXILIARY_TEXT,
            fields=("【脚注 1】1.1 此编号属于脚注，不是产品条款",),
        ),
        _row(3, "2.2", "责任免除\n免责正文"),
    ))

    assert [clause.number for clause in content.clauses] == ["2", "2.1", "2.2"]
    assert content.clauses[1].text == (
        "正文第一段\n【脚注 1】1.1 此编号属于脚注，不是产品条款"
    )
    assert content.unclassified_sections == ()
    assert content.coverage_attestation.coverage_attested


def test_note_without_active_clause_remains_standalone_evidence():
    content = assemble_numbered_content((
        SourceRecord(
            0,
            SourceRecordKind.AUXILIARY_TEXT,
            fields=("【脚注 1】前置说明",),
        ),
        _row(1, "1", "保险责任\n正文"),
    ))

    assert content.clauses[0].text == "正文"
    assert content.unclassified_sections[0].content == "【脚注 1】前置说明"


def test_reading_guide_and_appendix_are_auxiliary_blocks_in_source_order():
    table = DataTable(
        data=[["保障责任", "限额"], ["医疗", "100万"]],
        table_type=TableType.OTHER,
        raw_text="保障责任\t限额\n医疗\t100万",
        table_index=1,
    )
    content = assemble_numbered_content((
        SourceRecord(
            0, SourceRecordKind.TEXT, fields=("阅读指引",),
        ),
        SourceRecord(
            1, SourceRecordKind.TABLE_ROW,
            fields=("请仔细阅读本条款。",),
        ),
        _row(2, "1", "被保险人范围"),
        _row(3, "1.1", "投保范围\n正文"),
        SourceRecord(
            4, SourceRecordKind.TEXT, fields=("附表一：",),
        ),
        SourceRecord(
            5, SourceRecordKind.TEXT, fields=("保障计划表",),
        ),
        SourceRecord(
            6, SourceRecordKind.DATA_TABLE, data_table=table,
        ),
    ))
    document = AuditDocument(
        file_name="测试.docx",
        file_type=".docx",
        clauses=content.clauses,
        tables=content.tables,
        unclassified_sections=content.unclassified_sections,
        notices=content.notices,
    )

    assert content.notices[0].content == "请仔细阅读本条款。"
    assert content.tables[0].remark == "附表一：\n保障计划表"
    assert [block.block_type for block in document.audit_blocks] == [
        AuditBlockType.NOTICE,
        AuditBlockType.CLAUSE,
        AuditBlockType.CLAUSE,
        AuditBlockType.TABLE,
    ]


def test_clause_id_is_independent_of_layout_coordinates():
    first = AuditDocument(
        file_name="一.docx",
        file_type=".docx",
        clauses=assemble_numbered_content((
            SourceRecord(
                0,
                SourceRecordKind.TEXT,
                fields=("1.1 等待期 等待期为30日",),
                page_number=1,
                bbox=(1, 2, 3, 4),
            ),
        )).clauses,
    )
    second = AuditDocument(
        file_name="二.pdf",
        file_type=".pdf",
        clauses=assemble_numbered_content((
            SourceRecord(
                9,
                SourceRecordKind.TEXT,
                fields=("1.1 等待期 等待期为30日",),
                page_number=7,
                bbox=(9, 8, 7, 6),
            ),
        )).clauses,
    )

    assert first.audit_blocks[0].clause_id == second.audit_blocks[0].clause_id
