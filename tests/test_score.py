"""Tests for the candidate scoring."""

from __future__ import annotations

import pytest

from spoti_cl.match.canonical import Canonical
from spoti_cl.match.score import score_candidate
from spoti_cl.models import Artist, Candidate, Track


def make_track(
    title: str,
    artist: str = "Rick Astley",
    duration_ms: int = 213_573,
    isrc: str = "",
) -> Track:
    return Track(
        id="4cOdK2wGLETKBW3PvgPWqT",
        name=title,
        artists=[Artist(name=artist)],
        duration_ms=duration_ms,
        isrc=isrc,
    )


def make_candidate(
    title: str,
    duration: float | None = 213.0,
    uploader: str = "Rick Astley",
) -> Candidate:
    return Candidate(
        video_id="dQw4w9WgXcQ",
        title=title,
        duration=duration,
        uploader=uploader,
        channel=uploader,
    )


def test_exact_title_scores_high() -> None:
    score = score_candidate(make_track("Never Gonna Give You Up"), make_candidate("Never Gonna Give You Up"))
    assert score > 0.9


def test_official_video_wins_over_cover() -> None:
    track = make_track("Never Gonna Give You Up")
    official = make_candidate("Rick Astley - Never Gonna Give You Up (Official Music Video)")
    cover = make_candidate("Never Gonna Give You Up (Acoustic Cover)")
    assert score_candidate(track, official) > score_candidate(track, cover)


def test_cover_is_penalised() -> None:
    track = make_track("Creep", "Radiohead", 238_640)
    good = make_candidate("Radiohead - Creep", duration=238.0, uploader="Radiohead")
    bad = make_candidate("Creep (Cover By Some Band)", duration=238.0, uploader="Some Band")
    assert score_candidate(track, good) > score_candidate(track, bad)


def test_wrong_duration_is_rejected() -> None:
    track = make_track("Creep", "Radiohead", 238_640)
    candidate = make_candidate("Radiohead - Creep", duration=400.0, uploader="Radiohead")
    assert score_candidate(track, candidate) == 0.0


def test_topic_channel_gets_a_bonus() -> None:
    track = make_track("Creep", "Radiohead", 238_640)
    topic = make_candidate("Creep", duration=238.0, uploader="Radiohead - Topic")
    random = make_candidate("Creep", duration=238.0, uploader="Some Random Channel")
    assert score_candidate(track, topic) > score_candidate(track, random)


def test_canonical_title_is_used_when_available() -> None:
    # A release whose Spotify title does not match the recording title at all.
    track = make_track("Untitled 3", "Bonobo", 240_000)
    canonical = Canonical(title="Black Sands", artist="Bonobo", duration_ms=240_000)
    candidate = make_candidate("Bonobo - Black Sands", duration=240.0, uploader="Bonobo")
    with_canonical = score_candidate(track, candidate, canonical)
    without = score_candidate(track, candidate, None)
    assert with_canonical > without + 0.2


def test_featured_artist_does_not_break_matching() -> None:
    track = make_track("expectations (feat. Chappell Roan)", "Olivia Rodrigo", 223_000)
    candidate = make_candidate(
        "Olivia Rodrigo - expectations (feat. Chappell Roan)", duration=223.0, uploader="Olivia Rodrigo"
    )
    assert score_candidate(track, candidate) > 0.8


@pytest.mark.parametrize(
    "left,right,expected_min",
    [
        ("Creep", "Creep", 1.0),
        ("Creep", "Creep (Live)", 0.4),
        ("Creep", "Kreep", 0.2),
    ],
)
def test_similarity_bounds(left: str, right: str, expected_min: float) -> None:
    from spoti_cl.textutil import similarity

    assert similarity(left, right) >= expected_min
