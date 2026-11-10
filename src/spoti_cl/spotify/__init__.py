"""Spotify metadata access without credentials."""

from __future__ import annotations

from .client import SpotifyApiError, SpotifyClient
from .resolve import Resolver
from .session import SpotifyAuthError, SpotifySession

__all__ = [
    "SpotifyClient",
    "SpotifyApiError",
    "SpotifySession",
    "SpotifyAuthError",
    "Resolver",
]
