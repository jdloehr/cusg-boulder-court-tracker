from app.moderation import is_likely_spam_or_profane


def test_genuine_reflection_passes():
    text = (
        "The oral argument was tightly focused on one narrow question of statutory "
        "interpretation. The Chief Justice pressed both sides hard on the plain-text "
        "reading. Worth attending if you want to see appellate advocacy up close."
    )
    assert is_likely_spam_or_profane(text) is False


def test_profanity_is_flagged():
    assert is_likely_spam_or_profane("this hearing was total bullshit honestly") is True


def test_excessive_links_are_flagged():
    text = "check http://a.com and http://b.com and http://c.com and www.d.com"
    assert is_likely_spam_or_profane(text) is True


def test_repeated_character_filler_is_flagged():
    assert is_likely_spam_or_profane("aaaaaaaaaaaaaaaaaaaaaaaaaaaa") is True


def test_empty_text_is_not_flagged():
    assert is_likely_spam_or_profane("") is False
    assert is_likely_spam_or_profane(None) is False
