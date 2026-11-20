#!/usr/bin/env python3
"""Transcripten ophalen op een machine die YouTube niet blokkeert.

Leest de wachtrij (JSON-lijst van {"id", "titel"}) op stdin en schrijft per video één
JSON-regel naar stdout: {"id", "snippets": [[start, duur, tekst], ...]} of {"id", "geen": reden},
en tot slot {"klaar": true}. Weigert YouTube dit IP, dan volgt {"geblokkeerd": true} en stopt het script met code 2; wat al
binnen is, is dan al geschreven.

Alleen afhankelijk van youtube-transcript-api:
    python3 -m venv venv && venv/bin/pip install youtube-transcript-api
    ssh server 'brief wachtrij' | venv/bin/python haal_transcripten.py | ssh server 'brief lever'
"""
import argparse
import json
import sys
import time

from youtube_transcript_api import (IpBlocked, RequestBlocked, YouTubeTranscriptApi,
                                    YouTubeTranscriptApiException)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pauze", type=float, default=20, help="seconden tussen twee video's")
    a = p.parse_args()
    wachtrij = json.load(sys.stdin)
    api = YouTubeTranscriptApi()
    for i, v in enumerate(wachtrij):
        if i:
            time.sleep(a.pauze)
        try:
            t = api.fetch(v["id"], languages=["en", "en-US", "en-GB"])
            uit = {"id": v["id"], "snippets": [[s.start, s.duration, s.text] for s in t]}
        except (RequestBlocked, IpBlocked):
            print(json.dumps({"geblokkeerd": True}), flush=True)
            print(f"geblokkeerd bij {v['id']}", file=sys.stderr)
            return 2
        except YouTubeTranscriptApiException as e:
            uit = {"id": v["id"], "geen": f"{type(e).__name__}: {str(e)[:200]}"}
        print(json.dumps(uit, ensure_ascii=False), flush=True)
        print(f"{v['id']}: {'ok' if 'snippets' in uit else uit['geen'][:60]}", file=sys.stderr)
    print(json.dumps({"klaar": True}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
