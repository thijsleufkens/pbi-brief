"""YouTube: de video- en shortslijsten per kanaal (yt-dlp, plat) en de transcripten."""
from dataclasses import dataclass

import yt_dlp
from youtube_transcript_api import (IpBlocked, NoTranscriptFound, RequestBlocked, TranscriptsDisabled,
                                    VideoUnavailable, YouTubeTranscriptApi,
                                    YouTubeTranscriptApiException)

from . import config


class Geblokkeerd(RuntimeError):
    """YouTube weigert ons IP: geen video-probleem maar een dienst-probleem."""


class GeenTranscript(RuntimeError):
    """(Nog) geen transcript voor deze video; later opnieuw proberen."""


@dataclass
class Video:
    id: str
    titel: str
    duur_s: int | None  # None = premiere/live, nog onbekend


@dataclass
class Transcript:
    tekst: str        # met [mm:ss]-markers
    duur_s: int
    woorden: int
    afgekapt: bool


def parse_lijst(info: dict) -> list[Video]:
    uit = []
    for e in info.get("entries") or []:
        if e and e.get("id"):
            d = e.get("duration")
            uit.append(Video(e["id"], (e.get("title") or "").strip(), int(d) if d else None))
    return uit


def haal_lijst(url: str, n: int) -> list[Video]:
    """Nieuwste eerst. Een fout hier is een dienst-probleem: laat hem doorvallen."""
    opts = {"extract_flat": "in_playlist", "playlistend": n, "quiet": True,
            "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return parse_lijst(ydl.extract_info(url, download=False))


def mmss(sec: float) -> str:
    s = int(sec)
    u, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{u}:{m:02d}:{s:02d}" if u else f"{m:02d}:{s:02d}"


def bouw_tekst(snippets: list[tuple[float, float, str]], blok_s: int = config.BLOK_SECONDEN,
               max_woorden: int = config.MAX_WOORDEN) -> Transcript:
    """snippets = [(start, duur, tekst)] -> tekst met een [mm:ss]-marker per blok."""
    blokken, huidig, blok_start, woorden, afgekapt = [], [], None, 0, False
    for start, _, tekst in snippets:
        tekst = " ".join(tekst.replace("\n", " ").split())
        if not tekst:
            continue
        n = len(tekst.split())
        if woorden + n > max_woorden:
            afgekapt = True
            break
        if blok_start is None or start - blok_start >= blok_s:
            if huidig:
                blokken.append(f"[{mmss(blok_start)}] " + " ".join(huidig))
            huidig, blok_start = [], start
        huidig.append(tekst)
        woorden += n
    if huidig:
        blokken.append(f"[{mmss(blok_start)}] " + " ".join(huidig))
    duur = int(max((s + d for s, d, _ in snippets), default=0))
    return Transcript("\n".join(blokken), duur, woorden, afgekapt)


def haal_transcript(vid: str) -> Transcript:
    try:
        t = YouTubeTranscriptApi().fetch(vid, languages=["en", "en-US", "en-GB"])
    except (RequestBlocked, IpBlocked) as e:
        raise Geblokkeerd(type(e).__name__) from e
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as e:
        raise GeenTranscript(type(e).__name__) from e
    except YouTubeTranscriptApiException as e:  # leeftijdsgrens, onspeelbaar, parse-fout: per video
        raise GeenTranscript(f"{type(e).__name__}: {str(e)[:200]}") from e
    snippets = [(s.start, s.duration, s.text) for s in t]
    if not snippets:
        raise GeenTranscript("leeg transcript")
    return bouw_tekst(snippets)
