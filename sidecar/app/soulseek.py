"""Reuse slskd; bounded search/peers/transfers with shared-file verification."""

import asyncio
import httpx
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import quote
from .config import settings
from .providers import ProviderFailure, slskd_request, require_slskd_shared_directory
from .track_matching import normalize, matches, probe, media_file


async def download(wanted, output):
    state = await slskd_request("GET", "/server")
    if not state.get("isConnected") or not state.get("isLoggedIn"):
        raise ProviderFailure(
            "soulseek", "offline", "slskd is not connected/logged into Soulseek.", True
        )
    await require_slskd_shared_directory()
    search = await slskd_request(
        "POST",
        "/searches",
        json={
            "searchText": wanted["artist"] + " " + wanted["title"],
            # The installed daemon interpreted 5 as milliseconds despite its
            # API documentation. Use its default and stop the search in finally.
            "fileLimit": 100,
            "responseLimit": 20,
            "maximumPeerQueueLength": 5,
        },
    )
    sid = search["id"]
    try:
        await asyncio.sleep(8)
        responses = await slskd_request("GET", f"/searches/{sid}/responses")
        candidates = []
        for response in responses[:20]:
            for f in (response.get("files") or [])[:100]:
                name = f.get("filename") or ""
                raw = PureWindowsPath(name)
                if raw.suffix.lower() not in {".flac", ".ogg", ".mp3", ".m4a", ".wav"}:
                    continue
                title = normalize(raw.stem)
                artist = wanted["artist"]
                if not (" " + normalize(artist) + " ") in (" " + normalize(name) + " "):
                    continue
                # Strip only known artist/album and numeric track prefixes.
                # Keep version suffixes (clean/live/remix) for exact matching.
                title = re.sub(r"^(?:\d+\s+){1,2}", "", title)
                for prefix in (artist, wanted.get("album") or ""):
                    prefix = normalize(prefix)
                    if prefix and title.startswith(prefix + " "):
                        title = title[len(prefix) + 1 :]
                title = re.sub(r"^(?:\d+\s+){1,2}", "", title)
                length = f.get("length")
                for attr in f.get("attributes") or []:
                    if isinstance(attr, dict) and attr.get("type") in (1, "Length"):
                        length = attr.get("value")
                if not length or not matches(
                    wanted,
                    {"artist": artist, "title": title, "duration_seconds": length},
                ):
                    continue
                if (
                    not 15 <= float(length) <= 3600
                    or not 0 < int(f.get("size") or 0) <= 200_000_000
                ):
                    continue
                candidates.append((response["username"], f, float(length)))
        if not candidates:
            raise ProviderFailure(
                "soulseek",
                "no_match",
                "No Soulseek result matched artist, recording title/version and audio duration.",
            )
        if (
            not wanted.get("duration_seconds")
            and candidates
            and max(x[2] for x in candidates) - min(x[2] for x in candidates) > 5
        ):
            raise ProviderFailure(
                "soulseek",
                "ambiguous",
                "Different recordings share these filenames; provide accurate recording metadata.",
            )
        for username, f, length in candidates[:2]:
            transfer_id = None
            try:
                endpoint = "/transfers/downloads/" + quote(username, safe="")
                response = await slskd_request(
                    "POST",
                    endpoint,
                    json=[{"filename": f["filename"], "size": f["size"]}],
                )
                enqueued = response.get("enqueued") or []
                if not enqueued:
                    continue
                transfer_id = enqueued[0]["id"]
                async with asyncio.timeout(75):
                    while True:
                        transfer = await slskd_request(
                            "GET", endpoint + "/" + str(transfer_id)
                        )
                        state = str(transfer.get("state") or "")
                        if "Succeeded" in state:
                            break
                        if any(
                            v in state
                            for v in (
                                "Errored",
                                "Cancelled",
                                "Rejected",
                                "TimedOut",
                                "Aborted",
                            )
                        ):
                            break
                        await asyncio.sleep(3)
                if "Succeeded" not in state:
                    continue
                root = Path(settings.slskd_complete_path)
                basename = PureWindowsPath(f["filename"]).name
                files = [
                    p
                    for p in root.rglob("*")
                    if p.name == basename
                    and p.is_file()
                    and p.stat().st_size == f["size"]
                    and media_file(p, root)
                ]
                if len(files) != 1:
                    raise ProviderFailure(
                        "soulseek",
                        "shared_path",
                        "Transfer completed but could not locate one verified file under SLSKD_COMPLETE_PATH. Check slskd download directory and shared mount.",
                    )
                meta = await asyncio.to_thread(probe, files[0])
                if not meta or abs(meta["duration_seconds"] - length) > max(
                    5, length * 0.03
                ):
                    continue
                if meta.get("title") and not matches(
                    wanted, {**meta, "artist": meta.get("artist") or wanted["artist"]}
                ):
                    continue
                # Decode ordinary audio; ffmpeg cannot bypass DRM.
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-n",
                    "-i",
                    str(files[0]),
                    "-vn",
                    "-c:a",
                    "libvorbis",
                    str(output),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(proc.wait(), 45)
                except BaseException:
                    proc.kill()
                    await proc.wait()
                    raise
                if proc.returncode == 0:
                    return length
                output.unlink(missing_ok=True)
            except (TimeoutError, httpx.HTTPError, ProviderFailure) as exc:
                if isinstance(exc, ProviderFailure):
                    raise
            finally:
                if transfer_id:
                    try:
                        await slskd_request(
                            "DELETE",
                            endpoint + "/" + str(transfer_id),
                            params={"remove": "false"},
                        )
                    except Exception:
                        pass
        raise ProviderFailure(
            "soulseek",
            "peers_failed",
            "Matching Soulseek peers did not deliver valid audio within two bounded attempts.",
            True,
        )
    finally:
        try:
            await slskd_request("PUT", f"/searches/{sid}")
        except Exception:
            pass
