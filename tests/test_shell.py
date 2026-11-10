"""Tests for the interactive shell."""

from __future__ import annotations

from spoti_cl.shell import looks_like_link, split_command


def test_split_command_handles_quoted_urls() -> None:
    parts = split_command('get "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"')
    assert parts[0] == "get"
    assert parts[1] == "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"


def test_split_command_keeps_windows_paths() -> None:
    parts = split_command(r'get link -o C:\Users\mitkk\Music')
    assert parts[-1] == r"C:\Users\mitkk\Music"


def test_split_command_with_extra_spaces() -> None:
    assert split_command("  get   link  ") == ["get", "link"]


def test_looks_like_link() -> None:
    assert looks_like_link("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")
    assert looks_like_link("spotify:track:4cOdK2wGLETKBW3PvgPWqT")
    assert not looks_like_link("get")
    assert not looks_like_link("https://example.com/song")


def test_interactive_parser_reports_instead_of_exiting() -> None:
    from spoti_cl.cli import ShellUsageError, build_parser

    parser = build_parser(interactive=True)
    try:
        parser.parse_args(["nonsense"])
    except ShellUsageError as exc:
        assert "invalid choice" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("the interactive parser must not exit the process")


def test_interactive_parser_accepts_normal_commands() -> None:
    from spoti_cl.cli import build_parser

    parser = build_parser(interactive=True)
    args = parser.parse_args(["get", "https://open.spotify.com/track/abc", "-f", "mp3"])
    assert args.command == "get"
    assert args.format == "mp3"
    assert args.output is None


def test_bare_link_keeps_its_case(monkeypatch) -> None:
    """Spotify ids are case sensitive - the shell must not lower them."""
    from spoti_cl.shell import InteractiveShell

    shell = InteractiveShell.__new__(InteractiveShell)  # no network, no session
    captured: list[list[str]] = []

    def fake_run_command(parts):
        captured.append(parts)
        return False

    monkeypatch.setattr(shell, "run_command", fake_run_command)

    link = "https://open.spotify.com/track/70LcF31zb1H0PyJoS1Sx1r"
    shell.dispatch(link)

    assert captured == [["get", link]]
    assert captured[0][1] == link
