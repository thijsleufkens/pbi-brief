"""pbi-brief nacht | editie [--droog] | wachtrij | lever"""
import argparse
import re
import logging
import sys
import time
from datetime import date, datetime, timezone

import json
from pathlib import Path

from . import bron, config, db, extern, mail, postgram, samenvat, week
from .qwen import Qwen, QwenFout

log = logging.getLogger("pbibrief")


def schrijf_heartbeat(naam: str) -> None:
    if not config.HEARTBEAT_DIR:
        return
    try:
        (Path(config.HEARTBEAT_DIR) / naam).write_text(datetime.now(timezone.utc).isoformat())
    except OSError as e:
        log.warning("heartbeat %s: %s", naam, e)


REDMOND_TITEL = re.compile(r"\bupdate\b", re.I)


def ontdek_kanaal(con, kanaal: dict, voorrang: int, lang: list[bron.Video], kort: list[bron.Video]) -> int:
    """Nieuwe video's van één kanaal opslaan. Korter dan MIN_DUUR_S op de /videos-tab telt als
    short; premieres (duur onbekend) komen later terug. Nieuw kanaal: alleen de nieuwste lange
    video en short, de rest als 'genegeerd' zodat de achterstand niet in één editie belandt."""
    eerste = db.kanaal_is_nieuw(con, kanaal["naam"])
    lange = [v for v in lang if v.duur_s and v.duur_s >= config.MIN_DUUR_S]
    korte = kort + [v for v in lang if v.duur_s and v.duur_s < config.MIN_DUUR_S]
    nieuw = 0
    for soort, lijst, eerste_n in (("lang", lange, config.EERSTE_RUN_LANG), ("kort", korte, config.EERSTE_RUN_KORT)):
        for i, v in enumerate(lijst):
            rubriek = "redmond" if soort == "lang" and kanaal.get("rubriek") == "redmond" and REDMOND_TITEL.search(v.titel) else ""
            status = "genegeerd" if eerste and i >= eerste_n else "nieuw"
            if db.voeg_toe(con, v.id, v.titel, kanaal["naam"], soort, rubriek, voorrang, i, status, v.duur_s) and status == "nieuw":
                nieuw += 1
    return nieuw


def ontdek(con) -> int:
    """Per kanaal; één kapot kanaal mag de rest niet tegenhouden, allemaal kapot = dienstfout."""
    nieuw = mislukt = 0
    kanalen = config.kanalen()
    for i, k in enumerate(kanalen):
        base = k["url"].rstrip("/")
        try:
            lang = bron.haal_lijst(base + "/videos", config.LIJST_LANG)
            kort = bron.haal_lijst(base + "/shorts", config.LIJST_KORT) if k.get("shorts") else []
        except Exception as e:  # noqa: BLE001 - yt-dlp gooit van alles
            log.warning("%s: lijst mislukt: %s", k["naam"], str(e)[:200])
            mislukt += 1
            continue
        n = ontdek_kanaal(con, k, i, lang, kort)
        log.info("%s: %d nieuw", k["naam"], n)
        nieuw += n
        time.sleep(2)
    if kanalen and mislukt == len(kanalen):
        raise RuntimeError("geen enkele kanaallijst opgehaald")
    return nieuw


def nacht() -> int:
    con = db.open_db(config.DB_PATH)
    nieuw = ontdek(con)
    log.info("lijsten: %d nieuwe video's", nieuw)
    qwen = Qwen()
    klaar = opgehaald = wacht = 0
    for v in db.te_doen(con):
        if v["transcript"]:
            t = bron.Transcript(v["transcript"], v["duur_s"] or 0, v["woorden"] or 0, bool(v["afgekapt"]))
        elif config.TRANSCRIPTEN == "extern":
            wacht += 1
            continue
        else:
            if opgehaald >= config.NACHTBUDGET:
                log.info("nachtbudget (%d transcripten) op; rest volgende nacht", config.NACHTBUDGET)
                break
            if opgehaald:
                time.sleep(config.PAUZE_S)  # YouTube rate-limit: rustig aan
            try:
                t = bron.haal_transcript(v["id"])
            except bron.GeenTranscript as e:
                log.info("%s: geen transcript (%s), poging %d", v["id"], e, v["pogingen"] + 1)
                db.markeer_mislukt(con, v["id"], str(e), config.MAX_POGINGEN)
                continue
            opgehaald += 1
            db.bewaar_transcript(con, v["id"], t.tekst, t.duur_s, t.woorden, t.afgekapt)
        try:
            if v["soort"] == "kort":
                s, meta = samenvat.vat_kort_samen(qwen, v["titel"], t.tekst, v["kanaal"])
                regel = f"kort: {s['tip']} [{'bruikbaar' if s['bruikbaar'] else 'teaser'}]"
            else:
                s, meta = samenvat.vat_samen(qwen, v["titel"], t.tekst, t.duur_s, t.afgekapt,
                                             v["kanaal"], redmond=v["rubriek"] == "redmond")
                regel = f"{s['kop']} [{s['oordeel']}, {s['score']}/5]"
        except QwenFout as e:
            log.error("%s: qwen faalde: %s", v["id"], e)
            raise
        db.markeer_klaar(con, v["id"], s, t.duur_s, t.woorden)
        klaar += 1
        log.info("%s %s: %s %.0fs", v["kanaal"], v["id"], regel, meta["latency_s"])
    if wacht:
        log.info("%d video's wachten op een transcript van elders", wacht)
    log.info("nacht klaar: %d samengevat", klaar)
    schrijf_heartbeat("pbi-brief-nacht")
    return 0


def editie(droog: bool = False) -> int:
    con = db.open_db(config.DB_PATH)
    videos = db.voor_editie(con)
    vandaag = date.today()
    nummer = db.editienummer(con)
    if not videos:
        log.info("niets nieuws deze week; geen mail")
        if not droog:
            schrijf_heartbeat("pbi-brief-editie")
        return 0
    g = mail.groepeer(videos)
    intro = week.schrijf_intro([(f'{v["kanaal"]}: {v["titel"]}', json.loads(v["samenvatting"]))
                                for v in videos if v["status"] == "klaar" and v["soort"] == "lang"])
    if droog:
        pad = config.DATA_DIR / "voorbeeld.html"
        pad.write_text(mail.html_body(nummer, vandaag, g, intro), encoding="utf-8")
        print(mail.onderwerp(nummer, g))
        print(f"voorbeeld: {pad}")
        return 0
    if not mail.verstuur(nummer, vandaag, g, intro):
        log.error("mail niet verstuurd; editie niet vastgelegd")
        return 1
    db.leg_editie_vast(con, vandaag.isoformat(), [v["id"] for v in videos])
    postgram.bewaar_editie(mail.tekst_body(nummer, vandaag, g, intro), nummer)
    log.info("editie %d verstuurd: %d video's", nummer, len(videos))
    schrijf_heartbeat("pbi-brief-editie")
    return 0


def wachtrij() -> int:
    """Nieuwe video's opzoeken en de wachtrij voor transcripten van elders als JSON afdrukken."""
    con = db.open_db(config.DB_PATH)
    log.info("lijst: %d nieuw", ontdek(con))
    print(json.dumps(extern.wachtrij(con, config.NACHTBUDGET), ensure_ascii=False))
    return 0


def lever() -> int:
    """Transcripten van elders (JSON-regels op stdin) opslaan; de nacht vat ze samen."""
    con = db.open_db(config.DB_PATH)
    ok, geen, afloop = extern.lever(con, sys.stdin)
    log.info("geleverd: %d transcripten, %d zonder; %s", ok, geen, afloop)
    if afloop != "klaar":
        return 1
    schrijf_heartbeat("pbi-brief-transcripten")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="pbi-brief")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("nacht")
    sub.add_parser("wachtrij", help="wachtrij voor transcripten van elders (JSON op stdout)")
    sub.add_parser("lever", help="transcripten van elders opslaan (JSON-regels op stdin)")
    ed = sub.add_parser("editie")
    ed.add_argument("--droog", action="store_true", help="niet versturen, schrijf data/voorbeeld.html")
    a = p.parse_args(argv)
    if a.cmd == "nacht":
        return nacht()
    if a.cmd == "wachtrij":
        return wachtrij()
    if a.cmd == "lever":
        return lever()
    return editie(droog=a.droog)


if __name__ == "__main__":
    sys.exit(main())
