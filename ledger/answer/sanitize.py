"""Text from the model or a filing is shown as Markdown; it must not bring its own links."""

from __future__ import annotations

import re

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def strip_markdown_links(text: str) -> str:
    """Keep the words of ``[words](url)`` and ``![alt](url)``; drop the address.

    Citation markers such as ``[1]`` carry no address and are left alone (the UI adds the
    real links itself, from the sources the pipeline cited).
    """
    return _LINK.sub(r"\1", text)
