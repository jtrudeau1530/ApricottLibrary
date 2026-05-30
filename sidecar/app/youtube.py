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

log = logging.getLogger("youtube")

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


def enumerate_playlist(url: str) -> list[dict]:
    """Return [{video_id, title, channel, duration, thumbnail}] for the playlist.

    Uses yt-dlp's flat-extract mode so we don't download anything yet —
    just metadata for every video in the playlist.
    """
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        return []
    entries = info.get("entries") or []
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

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
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
