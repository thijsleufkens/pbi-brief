"""Transcripten van elders.

YouTube blokkeert datacenter-IP's vaak voor transcripten. Dan haalt een andere machine met een
gewoon thuis-IP (een Raspberry Pi volstaat) ze op: de server geeft een wachtrij, die machine
haalt de transcripten met extern/haal_transcripten.py en levert ze terug. Samenvatten blijft op
de server. Zie de README, "Transcripten van elders".
"""
import json

from . import bron, config, db


def wachtrij(con, n: int) -> list[dict]:
    """De eerstvolgende video's zonder transcript, in dezelfde volgorde als de nacht ze doet."""
    uit = []
    for v in db.te_doen(con):
        if v["transcript"]:
            continue
        uit.append({"id": v["id"], "titel": v["titel"]})
        if len(uit) >= n:
            break
    return uit


def lever(con, regels) -> tuple[int, int, str]:
    """JSON-regels van haal_transcripten.py verwerken: {"id", "snippets": [[start, duur, tekst]]},
    {"id", "geen": reden}, en als laatste {"klaar": true} of {"geblokkeerd": true}. Alleen video's
    die nog op een transcript wachten worden bijgewerkt. Geeft (opgeslagen, zonder transcript,
    afloop) met afloop "klaar", "geblokkeerd" of "onvolledig" (de ophaler is halverwege gestopt)."""
    ok = geen = 0
    afloop = "onvolledig"
    for regel in regels:
        regel = regel.strip()
        if not regel:
            continue
        r = json.loads(regel)
        if r.get("klaar") or r.get("geblokkeerd"):
            afloop = "klaar" if r.get("klaar") else "geblokkeerd"
            continue
        vid = str(r.get("id", ""))
        rij = con.execute("SELECT 1 FROM video WHERE id=? AND status='nieuw' AND transcript IS NULL",
                          (vid,)).fetchone()
        if not rij:
            continue
        snippets = [(float(s), float(d), str(t)) for s, d, t in r.get("snippets") or []]
        if snippets:
            t = bron.bouw_tekst(snippets)
            if t.tekst:
                db.bewaar_transcript(con, vid, t.tekst, t.duur_s, t.woorden, t.afgekapt)
                ok += 1
                continue
        db.markeer_mislukt(con, vid, str(r.get("geen") or "leeg transcript"), config.MAX_POGINGEN)
        geen += 1
    return ok, geen, afloop
