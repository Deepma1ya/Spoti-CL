"""Tests for the text normalisation helpers."""

from __future__ import annotations

from spoti_cl.textutil import (
    core_title,
    normalize,
    safe_filename,
    similarity,
    strip_feat,
    strip_variants,
    tokenize,
)


def test_normalize_strips_accents_and_case() -> None:
    assert normalize("Beyoncé") == "beyonce"
    assert normalize("  Hello   World ") == "hello world"


def test_strip_variants_removes_bracketed_suffix() -> None:
    assert strip_variants("Creep (Remastered 2011)") == "Creep"
    assert strip_variants("Creep [Official Audio]") == "Creep"


def test_strip_feat_removes_featured_credit() -> None:
    assert strip_feat("expectations (feat. Chappell Roan)") == "expectations"
    assert strip_feat("Song feat. Someone") == "Song"


def test_tokenize_drops_variant_words() -> None:
    tokens = tokenize("Creep (Remastered 2011)")
    assert "creep" in tokens
    assert "remastered" not in tokens
    assert "2011" in tokens


def test_core_title_is_comparable() -> None:
    assert core_title("Creep (Remastered 2011)") == core_title("Creep")


def test_similarity_is_symmetric_and_bounded() -> None:
    assert similarity("Creep", "Creep") == 1.0
    assert similarity("Creep", "Radiohead") == similarity("Radiohead", "Creep")
    assert 0.0 <= similarity("Creep", "Something Else Entirely") <= 1.0


def test_safe_filename_removes_reserved_characters() -> None:
    cleaned = safe_filename('AC/DC: Back in Black?')
    assert "/" not in cleaned
    assert ":" not in cleaned
    assert "?" not in cleaned
    assert safe_filename("") == "untitled"
