"""PHI guard: the Matrix platform hint allows Markdown tables (PHI's Matrix client renders them).

The fix lives in the product default, not in per-install ``platform_hints`` overrides.
"""
from plugins.platforms.matrix.adapter_hint import PLATFORM_HINT


def test_matrix_hint_allows_tables():
    assert "Do NOT use tables" not in PLATFORM_HINT
    assert "tables render" in PLATFORM_HINT


def test_matrix_hint_keeps_the_rest_of_the_guidance():
    for kept in ("MEDIA:/absolute/path/to/file", "~~strikethrough~~", "[descriptive text](url)"):
        assert kept in PLATFORM_HINT
