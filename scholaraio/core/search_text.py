"""Lossy text folding for search comparisons; never use for stored metadata."""

import unicodedata

_LATIN_STROKES = str.maketrans({"ø": "o", "ł": "l", "đ": "d"})


def fold_search_text(value: object) -> str:
    """Ignore case, combining accents, and common Latin stroked letters."""
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(char for char in text if unicodedata.category(char) != "Mn").translate(_LATIN_STROKES)
