"""YouTube playlist enumeration + audio download via yt-dlp.

Used by the YouTube import path. Audio is extracted to OGG Vorbis to match
the existing librespot-produced library — Jellyfin doesn't care about the
container, but keeping it uniform avoids surprises when we add bulk ops
(re-tag, transcode, etc.) later.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .config import settings

log = logging.getLogger("youtube")


def _cookies_path() -> Path:
    """Optional cookies.txt path. When present, every yt-dlp call uses it
    so YouTube treats requests as an authenticated browser session — the
    only reliable mitigation for the 'Sign in to confirm you're not a bot'
    challenge on a headless server."""
    return Path(settings.data_path) / "youtube_cookies.txt"


def has_cookies() -> bool:
    return _cookies_path().exists()


def _yt_dlp_common_opts() -> dict:
    """Options shared by every yt-dlp invocation in this module.

    YouTube's SABR streaming requires a PO Token to hand out playable format
    URLs — without one, every player_client returns zero formats. We rely on
    the bgutil-pot-provider service (a sibling container) plus the
    bgutil-ytdlp-pot-provider plugin to mint tokens on demand; the plugin is
    discovered automatically once installed, we only need to pass its base
    URL so it talks to the right container.
    """
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            # Smart-TV API path — accepts the web cookies file but uses a
            # different streaming endpoint that isn't (yet) forced into SABR.
            # ios is a fallback for videos tv rejects.
            "youtube": {"player_client": ["tv", "ios"]},
            "youtubepot-bgutilhttp": {"base_url": [settings.bgutil_pot_url]},
        },
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    if has_cookies():
        opts["cookiefile"] = str(_cookies_path())
    return opts

# Common YouTube title decorations we strip before searching Spotify.
_NOISE_PATTERNS = [
    r"\(Official\s*(Music\s*)?Video\)",
    r"\[Official\s*(Music\s*)?Video\]",
    r"\(Official\s*Audio\)",
    r"\[Official\s*Audio\]",
    r"\(Official\s*Lyric\s*Video\)",
    r"\[Official\s*Lyric\s*Video\]",
    r"\(Lyrics?\)",
    r"\[Lyrics?\]",
    r"\(HD\)",
    r"\[HD\]",
    r"\(HQ\)",
    r"\[HQ\]",
    r"\(Visualizer\)",
    r"\[Visualizer\]",
    r"\(Audio\)",
    r"\[Audio\]",
    r"\bft\.\s.*$",
    r"\bfeat\.\s.*$",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)


def parse_title(raw_title: str, channel: str) -> tuple[str, str]:
    """Best-effort split of a YouTube title into (artist, track).

    Most music titles follow "Artist - Track" or "Artist – Track" (en dash).
    When the title doesn't contain a separator, the channel name is used as
    the artist (works for "Topic" channels like "Linkin Park - Topic").
    """
    title = _NOISE_RE.sub("", raw_title).strip(" -–|:")
    for sep in [" - ", " – ", " — ", " | "]:
        if sep in title:
            artist, _, track = title.partition(sep)
            artist = artist.strip()
            track = track.strip()
            if artist and track:
                return artist, track
    artist = re.sub(r"\s*-\s*Topic\s*$", "", channel).strip() or channel.strip() or "Unknown"
    return artist, title or raw_title


def _normalize_playlist_url(url: str) -> str:
    """Coerce any URL containing a ?list= param into a pure playlist URL.

    A 'watch?v=X&list=Y' link enumerates only the single video, because
    yt-dlp treats it as a video page (the playlist is just context). We
    rewrite to 'youtube.com/playlist?list=Y' so it walks the whole list.
    """
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    if "list" in (qs := parse_qs(parsed.query)):
        playlist_id = qs["list"][0]
        return f"https://www.youtube.com/playlist?list={playlist_id}"
    return url


def enumerate_playlist(url: str) -> list[dict]:
    """Return [{video_id, title, channel, duration, thumbnail}] for the playlist.

    Uses yt-dlp's flat-extract mode so we don't download anything yet —
    just metadata for every video in the playlist.
    """
    import yt_dlp

    url = _normalize_playlist_url(url)
    opts = {
        **_yt_dlp_common_opts(),
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        log.warning("yt-dlp returned no info for %s", url)
        return []
    entries = info.get("entries") or []
    log.info(
        "yt-dlp enumerate %s: type=%s entries=%d title=%s",
        url, info.get("_type"), len(entries), info.get("title"),
    )
    out: list[dict] = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        out.append(
            {
                "video_id": e["id"],
                "title": e.get("title") or "",
                "channel": e.get("channel") or e.get("uploader") or "",
                "duration": e.get("duration"),
                "thumbnail": _best_thumbnail(e),
                "url": e.get("url") or f"https://www.youtube.com/watch?v={e['id']}",
            }
        )
    return out


def _best_thumbnail(entry: dict) -> str | None:
    thumbs = entry.get("thumbnails") or []
    if thumbs:
        return max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0)).get("url")
    return entry.get("thumbnail")


def download_audio(video_id: str, output_path: Path) -> Path:
    """Download the audio track for video_id, writing OGG Vorbis to output_path.

    Sync; call via asyncio.to_thread. ffmpeg must be installed.
    """
    import yt_dlp

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # yt-dlp adds its own extension after postprocessing — strip the .ogg we
    # were given and let it produce <stem>.ogg via the FFmpegExtractAudio
    # postprocessor.
    out_template = str(output_path.with_suffix(""))

    # Format selector: prefer audio-only, accept any video as fallback. The
    # FFmpegExtractAudio postprocessor strips audio out of whichever container
    # we end up with.
    opts = {
        **_yt_dlp_common_opts(),
        # Simplest selector — let yt-dlp pick the best audio if one exists,
        # otherwise the best combined stream that FFmpegExtractAudio can pull
        # audio from. Avoids over-constrained filters that surface as
        # 'Requested format is not available'.
        "format": "ba/b",
        "outtmpl": out_template + ".%(ext)s",
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "vorbis",
                "preferredquality": "0",  # highest VBR
            },
        ],
    }

    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    produced = output_path.with_suffix(".ogg")
    if not produced.exists():
        # Some yt-dlp versions keep the temporary container — fall back to
        # whatever single file landed at out_template.*.
        matches = list(output_path.parent.glob(output_path.stem + ".*"))
        if not matches:
            raise RuntimeError(f"yt-dlp produced no audio for {video_id}")
        produced = matches[0]
        produced = produced.rename(output_path.with_suffix(".ogg"))
    return produced
