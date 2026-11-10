"""Finding the best audio source for a Spotify recording."""

from __future__ import annotations

from .canonical import Canonical, lookup_isrc
from .candidates import search_candidates
from .engine import Match, Matcher, MatchError
from .score import score_candidate

__all__ = [
    "Canonical",
    "lookup_isrc",
    "search_candidates",
    "Matcher",
    "Match",
    "MatchError",
    "score_candidate",
]
