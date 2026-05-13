"""Pure text-matching helpers used by the search tools.

The matching strategy is intentionally simple for Phase 1: lowercase
the query, split on whitespace, treat the parts as terms, and require
every term to appear as a substring in the candidate text (AND
semantics). Score is the sum of term occurrences across the text.

This is title/excerpt search, not full-body search. The build plan
defers a real index to a later phase; this module's job is to be
predictable and easy to reason about, not clever.

No I/O, no dependencies, no async. Source adapters/tool wrappers
handle the network + caching layer.
"""

from __future__ import annotations


def tokenize(query: str) -> list[str]:
    """Lowercase the query and split into non-empty whitespace-separated terms.

    Punctuation is preserved (no special handling), which mirrors how an
    agent typically passes queries like "Anthropic Mythos" or "EU AI Act".
    """
    return [t for t in query.lower().split() if t]


def score_text(text: str, terms: list[str]) -> tuple[int, list[str]]:
    """AND-match `terms` against `text` (case-insensitive substring).

    Returns (score, matched_terms):
      - score is the sum of substring-occurrence counts across all terms,
        or 0 if any term is missing.
      - matched_terms is the input list preserved (or [] if score is 0).

    Both sides are lowercased internally so the caller doesn't need to
    pre-normalise (tokenize() already returns lowercased terms, but
    direct callers shouldn't trip on mixed case).

    Empty terms list returns (0, []) — the caller decides whether to
    short-circuit before scoring.
    """
    if not terms:
        return 0, []
    text_lower = text.lower()
    total = 0
    for term in terms:
        count = text_lower.count(term.lower())
        if count == 0:
            # AND semantics: a missing term means no match.
            return 0, []
        total += count
    return total, list(terms)
