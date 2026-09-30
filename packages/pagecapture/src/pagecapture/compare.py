"""How much of the rendered content the plain response already holds: the check that decides when plain HTTP is
enough (calibrated by benchmarks/comparison.py; docs/benchmarks.md).

Both sides become token windows. Rendered lines give 3-token windows (a shorter line counts as its whole token
sequence); the plain response's visible text gives 1–3-token windows, read both with and without spaces between
elements (browsers run adjacent inline elements together, e.g. menu items without whitespace in the markup).
"""

import re

from .document import Document

# Scripts written without spaces (CJK, Thai, ...) are compared character by character: where word breaks fall
# depends on markup (raw HTML text vs the browser's innerText), not on the content.
_TOKEN = re.compile(r"[぀-ヿ㐀-鿿豈-﫿가-힯฀-໿က-႟ក-៿]|[^\W_]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def rendered_shingles(lines) -> set[str]:
    """The rendered content as 3-token windows; a line shorter than that counts as its whole token sequence."""
    out: set[str] = set()
    for line in lines:
        t = _tokens(line)
        out |= {" ".join(t[i : i + 3]) for i in range(len(t) - 2)} if len(t) >= 3 else ({" ".join(t)} if t else set())
    return out


def text_shingles(*texts: str) -> set[str]:
    out: set[str] = set()
    for text in texts:
        t = _tokens(text)
        for n in (1, 2, 3):
            out |= {" ".join(t[i : i + n]) for i in range(len(t) - n + 1)}
    return out


def http_windows(page: Document) -> set[str]:
    """The plain response's visible text as token windows (reuses the text the classifier already extracted)."""
    return text_shingles(page.stats.text, page.stats.glued)


def coverage(http: set[str], rendered_lines) -> float:
    """Share of the rendered content (token windows) that the plain response already holds."""
    rendered = rendered_shingles(rendered_lines)
    return len(rendered & http) / len(rendered) if rendered else 1.0
