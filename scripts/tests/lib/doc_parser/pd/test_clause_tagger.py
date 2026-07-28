from lib.doc_parser.pd.clause_tagger import tag_clause_topics


def test_title_maps_to_controlled_topics():
    assert tag_clause_topics("保险期间和续保", "本合同不保证续保") == (
        "coverage.period", "renewal.general", "renewal.non_guaranteed",
    )


def test_unmatched_clause_is_not_guessed():
    assert tag_clause_topics("其他事项", "以批单约定为准") == ()
