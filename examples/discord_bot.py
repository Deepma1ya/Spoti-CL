"""A complete Discord bot built on top of spoti_cl.

Install the dependencies first::

    pip install -e ..
    pip install "discord.py>=2.3"

Then run it with a token in the environment::

    export DISCORD_TOKEN=your-bot-token
    python examples/discord_bot.py

Commands
--------
``!play <spotify link>``  queue and play a track, album or playlist
``!queue``                show what is queued
``!skip``                 skip the current track
``!stop``                 stop playback and clear the queue
``!now``                  show the current track

How the audio reaches Discord
-----------------------------
Discord voice speaks 48 kHz stereo signed 16 bit PCM. The bot therefore

1. asks spoti-cl for the direct media URL of the matched video,
2. runs ffmpeg on that URL to decode and resample it,
3. feeds the PCM into the voice connection.

The alternative is to run ``spoti-cl serve`` and point ffmpeg at
``http://127.0.0.1:8765/audio?url=<spotify link>`` instead - the bot below
supports both with ``SPOTICL_SERVICE`` set.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import discord
from discord.ext import commands

from spoti_cl import SpotiCL

SERVICE = os.environ.get("SPOTICL_SERVICE", "").strip()
FFMPEG = os.environ.get("FFMPEG_BINARY", "ffmpeg")


class FFmpegPCMAudio(discord.AudioSource):
    """Decode any media source into the PCM Discord voice expects."""

    def __init__(self, source: str, options: list[str] | None = None) -> None:
        super().__init__()
        self.source = source
        self.process: subprocess.Popen[bytes] | None = None
        self.options = options or []

    def load(self) -> None:
        self.process = subprocess.Popen(
            [FFMPEG, *self.options],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.read = self.process.stdout.read  # type: ignore[assignment]

    def cleanup(self) -> None:
        if self.process is not None:
            try:
                self.process.kill()
            except Exception:
                pass


class MusicBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix=commands.when_mentioned_or("!"))
        self.app = SpotiCL()
        self.queue: list[str] = []
        self.current: str | None = None
        self.voice: discord.VoiceProtocol | None = None
        self.play_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        await self.app.__aenter__() if hasattr(self.app, "__aenter__") else None

    async def on_ready(self) -> None:
        print(f"logged in as {self.user}")

    # ------------------------------------------------------------------ audio
    async def play_track(self, ctx: commands.Context, link: str) -> None:
        tracks = self.app.tracks(link)
        if not tracks:
            await ctx.send("nothing found at that link")
            return

        track = tracks[0]
        if self.voice is None or not self.voice.is_connected():
            channel = ctx.author.voice.channel
            if channel is None:
                await ctx.send("you have to be in a voice channel first")
                return
            self.voice = await channel.connect()

        await ctx.send(f"playing **{track.artist_label} - {track.name}**")

        source = await asyncio.to_thread(self.build_source, track.url)
        self.voice.play(source, after=lambda e: asyncio.create_task(self.after_play(e)))
        self.current = track.url

    def build_source(self, link: str) -> FFmpegPCMAudio:
        """Turn a Spotify link into something ffmpeg can read."""
        if SERVICE:
            target = f"{SERVICE.rstrip('/')}/audio?url={link}"
        else:
            info = self.app.stream_info(link)
            target = info.media_url
            headers = {"User-Agent": self.app.config.user_agent, **info.headers}
            options = ["-headers", "\r\n".join(f"{k}: {v}" for k, v in headers.items())]
            return FFmpegPCMAudio(
                target,
                ["-loglevel", "quiet", "-i", target, "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1"]
                + options,
            )

        return FFmpegPCMAudio(
            target,
            ["-loglevel", "quiet", "-i", target, "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1"],
        )

    async def after_play(self, error: Exception | None) -> None:
        if error:
            print(f"playback error: {error}")
        if self.queue:
            nxt = self.queue.pop(0)
            ctx = self.get_context(self.last_ctx) if hasattr(self, "last_ctx") else None
            if ctx is not None:
                await self.play_track(ctx, nxt)
        elif self.voice is not None:
            await self.voice.disconnect()

    # --------------------------------------------------------------- commands
    @commands.command(name="play")
    async def play(self, ctx: commands.Context, *, link: str) -> None:
        """Queue a Spotify track, album or playlist link."""
        await self.play_track(ctx, link)

    @commands.command(name="queue")
    async def queue(self, ctx: commands.Context) -> None:
        """Show the queue."""
        if not self.queue:
            await ctx.send("the queue is empty")
            return
        listing = "\n".join(f"{i}. {item}" for i, item in enumerate(self.queue, start=1))
        await ctx.send(listing)

    @commands.command(name="skip")
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the current track."""
        if self.voice is not None and self.voice.is_playing():
            self.voice.stop()
            await ctx.send("skipped")

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        """Stop playback."""
        self.queue.clear()
        if self.voice is not None:
            await self.voice.disconnect()
        await ctx.send("stopped")

    @commands.command(name="now")
    async def now(self, ctx: commands.Context) -> None:
        """Show the current track."""
        if self.current:
            tracks = self.app.tracks(self.current)
            if tracks:
                await ctx.send(f"now playing {tracks[0].artist_label} - {tracks[0].name}")
        else:
            await ctx.send("nothing is playing")


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("set DISCORD_TOKEN before running the bot", file=sys.stderr)
        raise SystemExit(1)
    intents = discord.Intents.default()
    intents.message_content = True
    bot = MusicBot()
    bot.run(token)


if __name__ == "__main__":
    main()
