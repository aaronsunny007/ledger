from ledger.answer.sanitize import strip_markdown_links


def test_links_and_images_lose_their_address_but_keep_their_words() -> None:
    text = "Revenue [1] rose, see [the filing](https://evil.example/x) ![pixel](https://evil.example/p?d=1)."
    assert strip_markdown_links(text) == "Revenue [1] rose, see the filing pixel."


def test_plain_text_and_citation_markers_are_untouched() -> None:
    text = "Net income was $5,070 million [1][2] (down 16.14%)."
    assert strip_markdown_links(text) == text
