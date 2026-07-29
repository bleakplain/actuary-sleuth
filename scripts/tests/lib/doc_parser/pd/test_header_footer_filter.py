from types import SimpleNamespace

from lib.doc_parser.pd.header_footer_filter import HeaderFooterFilter


def _char(text: str, x0: float, top: float) -> dict:
    return {
        "text": text,
        "x0": x0,
        "width": 5.0,
        "top": top,
        "bottom": top + 10.0,
    }


def test_baseline_offset_does_not_detach_clause_number_from_title():
    page = SimpleNamespace(chars=[
        *[
            _char(text, 10.0 + index * 5.0, 11.8)
            for index, text in enumerate("7.45")
        ],
        *[
            _char(text, 45.0 + index * 10.0, 10.0)
            for index, text in enumerate("开放性骨折")
        ],
    ])

    lines = HeaderFooterFilter()._build_lines_from_chars(page)

    assert len(lines) == 1
    assert lines[0][1].replace(" ", "") == "7.45开放性骨折"
