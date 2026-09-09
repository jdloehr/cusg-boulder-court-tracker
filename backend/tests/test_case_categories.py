from app.case_categories import decode_case_category, find_case_numbers_in_text
from app.models import CaseCategory


def test_known_prefixes_decode_correctly():
    cases = {
        "2026CR001452": CaseCategory.criminal,
        "2026M004410": CaseCategory.misdemeanor,
        "2026T005522": CaseCategory.traffic,
        "2026CV000980": CaseCategory.civil,
        "2026DR000221": CaseCategory.domestic_relations,
        "2026JV000045": CaseCategory.juvenile,
        "2026PR000089": CaseCategory.probate,
    }
    for case_number, expected in cases.items():
        result = decode_case_category(case_number)
        assert result.category == expected, case_number
        assert result.recognized is True


def test_small_claims_single_letter_prefix():
    # Found in real Boulder County data during build (e.g. "2025S165",
    # paired with "Hearing on Citation" / "Court Trial") -- not in the
    # build prompt's original table, added after live testing.
    result = decode_case_category("2025S165")
    assert result.category == CaseCategory.civil
    assert result.recognized is True


def test_case_insensitive_and_whitespace_tolerant():
    result = decode_case_category("2026 cr 001452")
    assert result.category == CaseCategory.criminal
    assert result.recognized is True


def test_unrecognized_prefix_falls_back_to_other_and_is_flagged():
    result = decode_case_category("2026XY000777")
    assert result.category == CaseCategory.other
    assert result.recognized is False


def test_empty_or_garbage_input_does_not_raise():
    assert decode_case_category("").recognized is False
    assert decode_case_category("not-a-case-number").recognized is False


def test_find_case_numbers_in_text_extracts_and_dedupes():
    text = (
        "The defendant's next hearing in case 2026CR001452 was continued. "
        "A related matter, 2026 CR 001452, was also mentioned, along with "
        "2026DR000221."
    )
    found = find_case_numbers_in_text(text)
    assert found == ["2026CR001452", "2026DR000221"]


def test_find_case_numbers_in_text_returns_empty_for_no_matches():
    text = "Sentencing was handed down Tuesday after a lengthy investigation."
    assert find_case_numbers_in_text(text) == []
