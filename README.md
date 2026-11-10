# Spoti-CL

**Spotify links in. High quality audio out.**

Spoti-CL takes a Spotify track, album, playlist or artist link and gives you the
audio — as a file, or as a live stream you can pipe straight into a Discord voice
channel. No Spotify client id. No OAuth. No account. No ads.

```bash
spoti-cl get "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" -o music
spoti-cl get "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" -o music -f mp3
spoti-cl stream "https://open.spotify.com/track/..." | ffmpeg -i pipe:0 -f s16le -ar 48000 pipe:1
```

---

## Interactive shell

Run it with no arguments and it opens a prompt that keeps one warm session
alive - the anonymous token, the metadata cache and the match cache stay hot
between commands, so the second command is as fast as the first.

```console
$ spoti-cl

  ____          _    _  _   _      _
/ ___|___  ___| | _(_) || |_(_)  / __|
\___ \ _ \/ __| |/ / | ||  _| \ \/ /
 ___) |  __/ (__|   <| || |___ \  /
|____/ \___|\___|_|\_|_||_|_/ /_/

  Spoti-CL 0.1.0
  Spotify links to high quality audio. No client id, no account.

  downloads go to E:\Projects\Spotify DRM free Commannd line
  paste a Spotify link to download it
  type help for commands, exit to quit

spoti-cl > https://open.spotify.com/track/70LcF31zb1H0PyJoS1Sx1r
1 track(s) queued -> E:\Projects\Spotify DRM free Commannd line\proof
format=best quality=320
ok E:\Projects\Spotify DRM free Commannd line\proof\Radiohead - Creep.webm

spoti-cl [proof] > get https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M -f mp3 -n 5
spoti-cl [proof] > play https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT
spoti-cl [proof] > serve --port 8765
spoti-cl [proof] > exit
```

**A bare Spotify link is a download.** Paste it, hit enter, done.

| Command | Does |
| --- | --- |
| `get <link>` | download a track, album, playlist or artist |
| `info <link>` | show metadata for a link |
| `stream <link>` | resolve the stream and print the media URL |
| `search <query>` | search Spotify (`-n`, `--type playlist`) |
| `serve` | run the HTTP service for bots (`--host`, `--port`) |
| `doctor` | check yt-dlp, ffmpeg, mutagen and the API |
| `config` | show or change the defaults (`--set k=v`) |

| Shell built-in | Does |
| --- | --- |
| `cd <dir>` | change where downloads land |
| `pwd` / `ls` | where you are / what is there |
| `play <link>` | stream the track straight through ffplay |
| `history` | the command history |
| `verbose [on\|off]` | toggle the chatty output |
| `clear` / `exit` | clear the screen / leave |

Tab completion covers command names, flags and paths. History is persisted
between sessions. A typo prints an error and keeps the shell alive.

---

## How it works without a Spotify client id

Spotify's official Web API needs a client id and a secret that belong to a
registered application. Spoti-CL never asks for either. Instead it uses the same
anonymous surface the Spotify web player and the embed player use:

| Need | How it is satisfied |
| --- | --- |
| Session token | The embed page (`open.spotify.com/embed/...`) hands out an anonymous bearer token to anybody who loads it. Spoti-CL reads it out of the page's `__NEXT_DATA__` payload. |
| Track metadata | Spotify's PathFinder GraphQL gateway (`api-partner.spotify.com`) serves complete track, album and playlist contents to anonymous callers. |
| ISRC | Spotify's `/v1/tracks/{id}` answers `429 QUOTA_EXCEEDED` for anonymous tokens, so the ISRC is cross referenced through MusicBrainz instead (see below). |
| Search | The one Web API endpoint that still answers anonymous callers is `/v1/search`, which Spoti-CL uses for `spoti-cl search`. |
| Query hashes | PathFinder queries are addressed by SHA-256 *persisted query* hash. Those hashes are published inside the public web player bundle. Spoti-CL parses them out of the bundle at runtime and caches them, so an upstream bundle rotation does not break the tool. There is no hardcoded hash to go stale. |
| Audio | The recording is located on YouTube with `yt-dlp` and pulled at the highest bitrate the source offers, then converted with `ffmpeg` if you ask for mp3 or flac. |

Nothing is scraped from a logged-in session and no cookie is required.

---

## Install

Requires Python 3.10+, `ffmpeg` on the PATH, and network access.

```bash
git clone https://github.com/Deepma1ya/Spoti-CL.git
cd Spoti-CL
python -m venv .venv
.venv/Scripts/activate        # Windows
source .venv/bin/activate     # macOS / Linux
pip install -e .
spoti-cl doctor               # checks yt-dlp, ffmpeg, mutagen and the API
```

`pip install -e .` pulls in `yt-dlp`, `httpx` and `mutagen`. `ffmpeg` has to be
installed separately (`winget install Gyan.FFmpeg`, `brew install ffmpeg`,
`apt install ffmpeg`).

The command is installed as `spoti-cl`. A `spotidl` alias is installed alongside
it, so either name works.

---

## Commands

```
spoti-cl                                     open the interactive shell
spoti-cl info <link>              metadata for a link, --json for machine output
spoti-cl get  <link>              download a track, album, playlist or artist
spoti-cl stream <link>            raw audio bytes on stdout
spoti-cl serve                    HTTP service for bots and other programs
spoti-cl search "<query>"         search the Spotify catalogue
spoti-cl doctor                   verify the environment
spoti-cl config [--set k=v ...]   inspect or change the defaults
```

### Downloading

```bash
# best quality, source container untouched (no re-encode, no quality loss)
spoti-cl get "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"

# 320 kbps mp3, parallel, first 20 tracks of a playlist only
spoti-cl get "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M" \
    -o music -f mp3 -q 320 -t 6 -n 20

# lossless container for archiving
spoti-cl get "https://open.spotify.com/album/5Z9iiGl2FcIfa3BMiv6OIw" -o music -f flac

# also stamp the ISRC into the tags (slower, cross references MusicBrainz)
spoti-cl get "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b" --isrc
```

Files are named `Artist - Title.ext`, tagged with title / artist / album /
track number / year, and carry the cover art.

| Format | Behaviour |
| --- | --- |
| `best` | Keeps the source container (`m4a`, `webm`, `opus`). No re-encode. |
| `mp3` | Transcoded with ffmpeg, 320 kbps by default (`-q`). |
| `flac` | Lossless container. |
| `opus`, `m4a`, `aac`, `wav` | Transcoded with ffmpeg. |

### Searching

```bash
spoti-cl search "radiohead creep"          # tracks
spoti-cl search "lofi beats" --type playlist
spoti-cl search "creep" --json             # machine readable
```

### Streaming

```bash
# raw stream to stdout - pipes into ffmpeg, ffplay, vlc, ...
spoti-cl stream "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT" \
  | ffplay -autoexit -nodisp -i pipe:0
```

For Discord and other bots, run the service instead:

```bash
spoti-cl serve --host 127.0.0.1 --port 8765
```

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | liveness probe |
| `GET /resolve?url=<link>` | JSON manifest of a track, album or playlist |
| `GET /search?q=<query>&limit=10` | JSON list of Spotify tracks |
| `GET /search?q=<query>&type=playlist` | JSON list of Spotify playlists |
| `GET /audio?url=<link>` | the audio itself, streamed, `Range` aware |

`/audio` also returns the metadata a bot needs in headers:

```
X-Spotify-Id, X-Spotify-Title, X-Spotify-Artist, X-Spotify-Album,
X-Spotify-Duration, X-Spotify-Cover, X-Spotify-Url, X-Match-Id, X-Match-Score
```

---

## Python API

```python
from spoti_cl import SpotiCL

app = SpotiCL()

tracks = app.tracks("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
match  = app.match(tracks[0])            # best YouTube source + score
info   = app.stream_info(tracks[0].url)   # direct media URL

for chunk in app.stream(tracks[0].url):   # audio bytes
    ...

app.download("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT", "music")
```

### Discord bot

`examples/discord_bot.py` is a complete `discord.py` bot. The important part:

```python
info = await app.stream_info(url)
headers = {"User-Agent": app.config.user_agent, **info.headers}

process = await asyncio.create_subprocess_exec(
    "ffmpeg",
    "-loglevel", "quiet",
    "-i", info.media_url,
    "-f", "s16le", "-ar", "48000", "-ac", "2",
    "pipe:1",
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
)
await voice_conn.play(
    source=ffmpeg_stream(process.stdout),
    before_secs=0.0,
)
```

Discord voice wants 48 kHz stereo s16le, so the raw stream is handed to ffmpeg
and the ffmpeg output is handed to Discord. `/audio` on the local service does
the same job over HTTP if you would rather not open the process.

---

## Matching quality

Finding "the same recording" on YouTube is the hard part of any tool like this.
Spoti-CL does it in layers:

1. **Canonical metadata** — the recording is looked up in MusicBrainz (free,
   no key) by title and artist, or by ISRC when one is known. That gives the
   canonical title, artist and length of the exact master, no matter what noise
   the Spotify title carries ("Remastered 2011", "feat. X", an alternative
   release title).
2. **Query ladder** — several search strings are tried in order, from
   `Artist - Title` through `Artist Title official audio`.
3. **Scoring** — every candidate is scored on title similarity, artist match,
   duration distance, channel trust (`- Topic`, official uploads, VEVO) and a
   penalty list for covers, live takes, remixes, karaoke, sped-up edits,
   nightcore, bass boosts, lyric videos and reaction videos.

The winner is cached for 30 days, so a playlist only pays the search cost once.
Canonical metadata is cached for 180 days.

### About the ISRC

Spotify's own catalogue endpoints (`/v1/tracks/{id}`, `/v1/albums/{id}`)
answer `429 QUOTA_EXCEEDED` for anonymous callers, so the ISRC cannot be read
straight from Spotify. Spoti-CL fills the gap with MusicBrainz, which
publishes ISRCs per recording. It only writes one into the tags when the
lengths agree, because the same song can exist as a single and as an album
track with different ISRCs. Pass `--isrc` to look every track up; MusicBrainz
allows one request per second, so it is off by default and the results are
cached.

---

## Configuration

`spoti-cl config` prints the current settings, `spoti-cl config --set k=v`
changes them. They live in `%APPDATA%\spoti-cl\config.json` (Windows) or
`~/.config/spoti-cl/config.json` (macOS / Linux).

| Key | Default | Meaning |
| --- | --- | --- |
| `format` | `best` | default output format |
| `quality` | `320` | bitrate for lossy formats |
| `threads` | `4` | parallel downloads |
| `output` | `downloads` | default output directory |
| `embed_cover` | `true` | embed cover art |
| `embed_metadata` | `true` | write tags |
| `min_score` | `0.62` | acceptance threshold for a match |
| `search_results` | `8` | candidates fetched per query |
| `match_timeout` | `25` | yt-dlp socket timeout |
| `cookie_file` | - | Netscape cookie file for yt-dlp |
| `proxy` | - | proxy URL passed to yt-dlp |

Environment overrides: `SPOTICL_FORMAT`, `SPOTICL_QUALITY`, `SPOTICL_THREADS`,
`SPOTICL_OUTPUT`, `SPOTICL_PROXY`, `SPOTICL_COOKIES`, `SPOTICL_MIN_SCORE`,
`SPOTICL_CACHE_DIR`.

---

## Layout

```
src/spoti_cl/
  cli.py            argparse front end
  shell.py          the interactive shell
  api.py            the public facade (SpotiCL)
  urls.py           link and URI parsing
  models.py         Track / Collection / Match / Candidate
  textutil.py       normalisation used by the matcher
  cache.py          JSON cache with TTL
  config.py         defaults, config file, env overrides
  server.py         HTTP service for bots
  spotify/
    session.py      anonymous token + runtime hash discovery
    client.py       PathFinder and Web API calls
    resolve.py      payloads -> models
  match/
    canonical.py    ISRC cross reference (Deezer, MusicBrainz)
    candidates.py   yt-dlp search
    score.py        candidate scoring
    engine.py       query ladder and caching
  audio/
    download.py     yt-dlp download, naming, batching
    tags.py         metadata and cover art (mutagen)
    stream.py       direct media URL and byte streaming
examples/discord_bot.py
tests/
```

---

## Notes and limits

- The tool reads *metadata* from Spotify and *audio* from YouTube. It never
  touches Spotify's encrypted audio stream, and it does not log into anything.
- Rate limits: Spotify throttles a burst of anonymous reads. Spoti-CL keeps its
  request count low (one embed page per entity, cached metadata, cached
  matches) and paginates playlists instead of asking for everything.
- Playlists longer than a page are paged through automatically.
- `best` means the highest bitrate the source video offers. YouTube caps most
  music uploads at roughly 130–160 kbps, so this is not CD quality - use
  `-f flac` for a lossless container, not for lossless audio.
- Podcasts and audiobook episodes are resolved as metadata but the matcher
  currently targets music recordings.
- Nothing here is affiliated with Spotify. Use it with material you have the
  right to use.

## Credits

The PathFinder persisted-query technique was found by reading the public
community implementations of the Spotify web client — notably
[SpotAPI](https://github.com/Aran404/SpotAPI) and
[spotifly](https://github.com/tr1ckydev/spotifly). The matching heuristics and
everything else in this repository are original.

MIT licensed.
