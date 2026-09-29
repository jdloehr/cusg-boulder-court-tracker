from app.hearing_types import TAG_COLORS, _RULES, classify_hearing_type
from app.models import HearingTypeCategory


def test_jury_trial_variants():
    for raw in ["Jury Trial", "JURY TRIAL", "Trial to Jury", "jury  trial - day 2"]:
        result = classify_hearing_type(raw)
        assert result.category == HearingTypeCategory.jury_trial, raw
        assert result.recognized is True


def test_oral_argument_and_motions_variants():
    for raw in ["Oral Argument", "Motions Hearing", "Motion Hearing", "Hearing on Motion to Suppress",
                "Motion to Modify Hearing", "Suppression Hearing"]:
        result = classify_hearing_type(raw)
        assert result.category == HearingTypeCategory.oral_argument_motions, raw


def test_known_other_types_are_recognized_not_flagged():
    for raw in ["Sentencing", "Arraignment", "Hearing on Advisement", "Return Date", "Status Conference"]:
        result = classify_hearing_type(raw)
        assert result.category == HearingTypeCategory.other
        assert result.recognized is True


def test_plain_language_display_matches_spec_example():
    result = classify_hearing_type("Oral Argument")
    assert "no witnesses or jury" in result.display


def test_unrecognized_type_is_flagged_for_review_not_dropped():
    result = classify_hearing_type("Zorbnax Compliance Review")  # not a real Colorado hearing type
    assert result.category == HearingTypeCategory.unrecognized
    assert result.recognized is False
    assert "Zorbnax Compliance Review" in result.display  # raw string preserved, not silently discarded


def test_competency_hearing_is_recognized_as_other_not_flagged():
    # Added after a real live pull surfaced "Competency to Proceed Hearing"
    # as a common raw value -- see hearing_types.py's post-build-data rules.
    result = classify_hearing_type("Competency to Proceed Hearing")
    assert result.category == HearingTypeCategory.other
    assert result.recognized is True


def test_blank_hearing_type_is_flagged():
    result = classify_hearing_type("")
    assert result.recognized is False


# --- Calendar-view doc: tag_color grouping -----------------------------------

def test_every_rule_uses_a_real_tag_color():
    """Every _RULES entry's 4th element must be one of the canonical
    TAG_COLORS keys -- catches a typo'd group name that would otherwise
    silently fall through to no matching CSS class on the frontend."""
    for pattern, _category, _display, tag_color in _RULES:
        assert tag_color in TAG_COLORS, f"{pattern.pattern!r} uses unknown tag_color {tag_color!r}"


def test_tag_color_spans_all_eight_groups_across_real_raw_strings():
    samples = {
        "Jury Trial": "jury_trial",
        "Oral Argument": "oral_argument",
        "Motions Hearing": "oral_argument",
        "Suppression Hearing": "oral_argument",
        "Bench Trial": "trial",
        "Sentencing": "sentencing",
        "Hearing on Revocation of Probation": "sentencing",
        "Arraignment": "arraignment",
        "Hearing on Advisement": "arraignment",
        "Return Date": "scheduling",
        "Status Conference": "scheduling",
        "Permanent Orders Hearing": "family_probate",
        "Paternity Hearing": "family_probate",
        "Competency to Proceed Hearing": "other",
    }
    for raw, expected_color in samples.items():
        result = classify_hearing_type(raw)
        assert result.tag_color == expected_color, raw
    assert set(samples.values()) == TAG_COLORS


def test_unrecognized_and_blank_default_to_other_tag_color():
    assert classify_hearing_type("Zorbnax Compliance Review").tag_color == "other"
    assert classify_hearing_type("").tag_color == "other"
