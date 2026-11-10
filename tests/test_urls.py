"""Tests for the link parser."""

from __future__ import annotations

import pytest

from spoti_cl.urls import SpotifyLinkError, is_spotify_link, parse_link


@pytest.mark.parametrize(
    "value,kind,identifier",
    [
        (
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc123",
            "track",
            "4cOdK2wGLETKBW3PvgPWqT",
        ),
        (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "playlist",
            "37i9dQZF1DXcBWIGoYBM5M",
        ),
        (
            "http://play.spotify.com/album/5Z9iiGl2FcIfa3BMiv6OIw/",
            "album",
            "5Z9iiGl2FcIfa3BMiv6OIw",
        ),
        (
            "https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT",
            "track",
            "4cOdK2wGLETKBW3PvgPWqT",
        ),
        ("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", "playlist", "37i9dQZF1DXcBWIGoYBM5M"),
        ("4cOdK2wGLETKBW3PvgPWqT", "track", "4cOdK2wGLETKBW3PvgPWqT"),
        ("  <https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT>  ", "track", "4cOdK2wGLETKBW3PvgPWqT"),
    ],
)
def test_parse_link(value: str, kind: str, identifier: str) -> None:
    ref = parse_link(value)
    assert ref.kind == kind
    assert ref.id == identifier
    assert ref.uri == f"spotify:{kind}:{identifier}"
    assert ref.url.endswith(f"/{kind}/{identifier}")


def test_parse_link_rejects_garbage() -> None:
    with pytest.raises(SpotifyLinkError):
        parse_link("https://example.com/song")
    with pytest.raises(SpotifyLinkError):
        parse_link("")


def test_is_spotify_link() -> None:
    assert is_spotify_link("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")
    assert not is_spotify_link("nope")
