"""Scoring of YouTube candidates against a Spotify track.

The goal is to pick the video that carries the same master recording, in the
best possible quality, and to reject the endless parade of covers, live
bootlegs, sped up edits and lyric videos that dominate a naive search.
"""

from __future__ import annotations

from ..models import Candidate, Track
from ..textutil import contains_phrase, core_title, similarity, tokenize
from .canonical import Canonical

#: Words in a candidate title that usually mean "not the master recording".
VARIANT_MARKERS = (
    "cover",
    "covers",
    "live",
    "remix",
    "bootleg",
    "karaoke",
    "instrumental",
    "sped up",
    "speed up",
    "slowed",
    "reverb",
    "nightcore",
    "8d audio",
    "loop",
    "mashup",
    "reaction",
    "tutorial",
    "review",
    "lyrics video",
    "lyric video",
    "lyrics",
    "audio only",
    "visualizer",
    "full album",
    "full song album",
    "concert",
    "unplugged",
    "acoustic",
    "demo",
    "bass boosted",
    "bass boost",
    "ringtone",
    "snippet",
    "preview",
    "music box",
    "piano cover",
    "violin cover",
    "8d",
    "sped",
    "vip",
)

#: Channel names that usually mean "this is the label / artist upload".
TRUSTED_CHANNELS = (
    "vevo",
    "official",
    "topic",
    "records",
    "music",
    "audio",
    "sound",
)

#: Duration deltas in seconds and the score they earn.
DURATION_TOLERANT = 2.0
DURATION_ACCEPT = 8.0
DURATION_FAR = 25.0


def _duration_score(expected_seconds: float, actual: float | None) -> float:
    if actual is None or expected_seconds <= 0:
        return 0.45
    delta = abs(actual - expected_seconds)
    if delta <= DURATION_TOLERANT:
        return 1.0
    if delta <= DURATION_ACCEPT:
        span = DURATION_ACCEPT - DURATION_TOLERANT
        return 1.0 - 0.45 * ((delta - DURATION_TOLERANT) / span)
    if delta <= DURATION_FAR:
        span = DURATION_FAR - DURATION_ACCEPT
        return 0.55 - 0.35 * ((delta - DURATION_ACCEPT) / span)
    return 0.0


def _artist_score(track: Track, candidate: Candidate, canonical: Canonical | None) -> float:
    """How well do the artists of the track line up with the candidate."""
    haystacks = [candidate.title, candidate.uploader, candidate.channel]
    names = list(track.artist_names)
    if canonical and canonical.artist:
        names.append(canonical.artist)

    best = 0.0
    for name in names:
        if not name:
            continue
        for haystack in haystacks:
            if not haystack:
                continue
            score = similarity(name, haystack)
            if contains_phrase(haystack, name):
                score = max(score, 0.95)
            best = max(best, score)
    return min(best, 1.0)


def _title_score(track: Track, candidate: Candidate, canonical: Canonical | None) -> float:
    """How well do the titles line up."""
    scores = [similarity(track.name, candidate.title)]
    if canonical and canonical.title:
        scores.append(similarity(canonical.title, candidate.title))
    # The candidate title often starts with "Artist - Title".
    for artist in track.artist_names:
        if artist and artist.lower() in candidate.title.lower():
            trimmed = candidate.title.lower().split(artist.lower(), 1)[-1]
            scores.append(similarity(track.name, trimmed.strip(" -_:")))
    return max(scores) if scores else 0.0


def _variant_penalty(track: Track, candidate: Candidate, canonical: Canonical | None) -> float:
    """Penalise candidates that announce themselves as a different variant."""
    expected = core_title(track.name)
    if canonical and canonical.title:
        expected = expected + " " + core_title(canonical.title)
    expected_tokens = set(tokenize(expected))

    title = candidate.title.lower()
    penalty = 0.0
    for marker in VARIANT_MARKERS:
        if marker in title:
            marker_tokens = set(tokenize(marker))
            if marker_tokens and marker_tokens.issubset(expected_tokens):
                # The recording really is a live take or a remix - no penalty.
                continue
            penalty += 0.16
    return min(penalty, 0.5)


def _channel_bonus(track: Track, candidate: Candidate) -> float:
    source = candidate.source.lower()
    bonus = 0.0
    if "topic" in source:
        bonus += 0.06
    elif any(marker in source for marker in TRUSTED_CHANNELS):
        bonus += 0.03
    for artist in track.artist_names:
        if artist and artist.lower() in source:
            bonus += 0.05
            break
    return bonus


def score_candidate(
    track: Track,
    candidate: Candidate,
    canonical: Canonical | None = None,
) -> float:
    """Score a candidate video against ``track`` in the 0..1 range."""
    if candidate.duration is not None and track.duration_ms:
        delta = abs(candidate.duration - track.duration_seconds)
        if delta > DURATION_FAR:
            # Completely different length - not this recording.
            return 0.0

    title_score = _title_score(track, candidate, canonical)
    artist_score = _artist_score(track, candidate, canonical)
    duration_score = _duration_score(track.duration_seconds, candidate.duration)

    score = 0.46 * title_score + 0.30 * artist_score + 0.24 * duration_score
    score -= _variant_penalty(track, candidate, canonical)
    score += _channel_bonus(track, candidate)

    if canonical and canonical.duration_ms and candidate.duration is not None:
        canonical_delta = abs(candidate.duration - canonical.duration_ms / 1000.0)
        if canonical_delta <= DURATION_TOLERANT:
            score += 0.05
        elif canonical_delta > DURATION_ACCEPT:
            score -= 0.10

    return max(0.0, min(1.0, score))
