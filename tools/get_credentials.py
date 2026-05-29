#!/usr/bin/env python3
"""
Generate librespot credentials.json by running Spotify's OAuth flow on your local machine.

One-time setup. Output is the credentials file the Library sidecar uses to stream
audio from your Spotify Premium account.

Usage:
    pip install librespot
    python3 tools/get_credentials.py

A URL is printed. Open it, sign in to Spotify, authorize. The local callback
captures the result and writes credentials.json in the current directory.

Then upload it to the sidecar:
    curl -X POST https://api.library.zektek.us/auth/librespot/credentials \\
         -H "content-type: application/json" \\
         --data-binary @credentials.json
"""
import sys
from pathlib import Path


def main() -> int:
    try:
        from librespot.core import Session
    except ImportError:
        print("librespot is not installed. Run: pip install librespot", file=sys.stderr)
        return 1

    out = Path.cwd() / "credentials.json"

    def callback(url: str) -> None:
        print("\nOpen this URL in your browser and sign in to Spotify:\n")
        print(f"  {url}\n")

    builder = Session.Builder()
    builder.conf.stored_credentials_file = str(out)
    builder.oauth(callback)
    session = builder.create()

    print(f"\nWrote {out}")
    print("Upload it to the sidecar:")
    print(
        "  curl -X POST https://api.library.zektek.us/auth/librespot/credentials \\\n"
        "       -H 'content-type: application/json' \\\n"
        f"       --data-binary @{out.name}"
    )

    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
