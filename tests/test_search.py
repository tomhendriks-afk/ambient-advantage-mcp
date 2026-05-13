"""Unit tests for the pure search-matching helpers in app.search."""

from __future__ import annotations

import pytest

from app import search


# --------------------------------------------------------------------------- #
# tokenize                                                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("query,expected", [
    ("",            []),
    ("   ",         []),
    ("Anthropic",   ["anthropic"]),
    ("EU AI Act",   ["eu", "ai", "act"]),
    ("Claude 4.6",  ["claude", "4.6"]),         # punctuation preserved
    ("  spaced  ",  ["spaced"]),
    ("Mixed CASE",  ["mixed", "case"]),         # lowercased
])
def test_tokenize_lowercases_and_splits(query, expected):
    assert search.tokenize(query) == expected


# --------------------------------------------------------------------------- #
# score_text — AND semantics                                                  #
# --------------------------------------------------------------------------- #

def test_score_text_returns_zero_for_empty_terms():
    score, matched = search.score_text("any text", [])
    assert (score, matched) == (0, [])


def test_score_text_scores_single_term_by_occurrence_count():
    score, matched = search.score_text("foo foo bar foo", ["foo"])
    assert score == 3
    assert matched == ["foo"]


def test_score_text_and_match_requires_every_term():
    # Both terms present → score is sum of counts.
    score, matched = search.score_text("foo bar foo", ["foo", "bar"])
    assert score == 3  # 2 foo + 1 bar
    assert matched == ["foo", "bar"]


def test_score_text_returns_zero_when_any_term_missing():
    """AND semantics: if even one term is absent, the candidate doesn't match."""
    score, matched = search.score_text("foo bar baz", ["foo", "quux"])
    assert score == 0
    assert matched == []


def test_score_text_is_case_insensitive():
    score, matched = search.score_text(
        "Anthropic announced Claude 4.7", ["anthropic", "CLAUDE"],
    )
    assert score == 2
    assert matched == ["anthropic", "CLAUDE"]


def test_score_text_treats_terms_as_substrings():
    """'mythos' matches 'Mythos' inside 'Anthropic Mythos' — substring, not word."""
    score, matched = search.score_text("Anthropic Mythos", ["mythos"])
    assert score == 1
    assert matched == ["mythos"]


def test_score_text_term_can_match_inside_words():
    """Substring match: 'eu' matches inside 'Europe' as well as 'EU AI Act'."""
    score, matched = search.score_text(
        "EU AI Act regulates Europe", ["eu"],
    )
    # "eu" appears in "EU" (lowered) and "europe" → 2 occurrences.
    assert score == 2
    assert matched == ["eu"]
