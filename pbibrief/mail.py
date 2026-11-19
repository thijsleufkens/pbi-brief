"""De wekelijkse mail: volledige inhoud, geen website. Tabel-layout met inline CSS (webfonts
en <style> worden in veel mailprogramma's genegeerd). Verzenden via Postmark. Geen tracking.

Vormgeving: een Power BI-rapportpagina. Bovenaan een grijs canvas met witte visuals: drie
kaarten (video's, kijktijd, kijktips) en een gestapelde staafgrafiek "kijktijd per kanaal" in
het standaardthema van Power BI. Daaronder de rubrieken in Segoe UI, de letter van Power BI.
Geel (#F2C811) is alleen vlak: kijktips, de streepjes in de tijdbalk en de 'Voor jou'-band.
Kleuren staan ook als bgcolor-attribuut zodat clients die omkeren het niet slopen."""
import html
import json
import logging
import os
from datetime import date

import httpx

from . import config
from .bron import mmss

log = logging.getLogger("pbibrief.mail")

SANS = "'Segoe UI', 'Segoe UI Web (West European)', -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', Arial, sans-serif"
CANVAS, PAPIER = "#F3F2F1", "#FFFFFF"
INKT, ZACHT, LIJN = "#252423", "#605E5C", "#E1DFDD"
DONKERBLAUW = "#12239E"                  # koppen-accent, links, labels (contrast ok als tekst)
GEEL, GEEL_BLEEK = "#F2C811", "#FFF8D6"  # alleen vlakken
REEKS = {"kijken": GEEL, "lezen": "#118DFF", "overslaan": "#C8C6C4", "redmond": DONKERBLAUW, "kort": "#E66C37"}
REEKS_NAAM = {"redmond": "maandupdate", "kijken": "kijken", "lezen": "lezen volstaat", "overslaan": "overslaan", "kort": "shorts"}
SECTIES = [("redmond", "Uit Redmond", "De maandupdates van Microsoft, als lijst met wat er nieuw is."),
           ("kijken", "Kijken", "De video zelf voegt iets toe. Spring naar de gemarkeerde momenten."),
           ("lezen", "Lezen volstaat", "Goede inhoud, maar dit is het meeste ervan."),
           ("kort", "Kort & handig", "Shorts, in één zin wat je ermee kunt."),
           ("overslaan", "Overslaan", "Niet voor jou, in één zin waarom.")]
OORDEEL_REEKS = {"kijken": "kijken", "samenvatting volstaat": "lezen", "overslaan": "overslaan"}
MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september",
           "oktober", "november", "december"]


def e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def yt(vid: str, sec: int | None = None, kort: bool = False) -> str:
    if kort:
        return f"https://www.youtube.com/shorts/{vid}"
    return f"https://www.youtube.com/watch?v={vid}" + (f"&t={sec}s" if sec else "")


def minuten(duur_s) -> str:
    return f"{round((duur_s or 0) / 60)} min" if duur_s else ""


def uren(sec: int) -> str:
    u, m = divmod(round(sec / 60), 60)
    return f"{u} u {m} min" if u else f"{m} min"


def uren_kort(sec: int) -> str:
    """Voor de kaarten: past ook op een telefoon in een derde van de breedte."""
    u, m = divmod(round(sec / 60), 60)
    return f"{u}:{m:02d} u" if u else f"{m} min"


def datum_nl(d: date) -> str:
    return f"{d.day} {MAANDEN[d.month - 1]} {d.year}"


def voor(s: dict) -> str:
    return s.get("voor_lezer") or ""


def _sleutel(vs):
    return (-vs[1]["score"], vs[0]["voorrang"], vs[0]["positie"])


def groepeer(videos) -> dict:
    """{'redmond'|'kijken'|'lezen'|'overslaan'|'kort': [(video, samenvatting)], 'geen': [...],
    'kort_rest': int}. Kijken heeft een harde grens (het model is een slechte beoordelaar)."""
    g = {k: [] for k, _, _ in SECTIES} | {"geen": [], "kort_rest": 0}
    for v in videos:
        if v["status"] != "klaar":
            if v["soort"] == "lang":
                g["geen"].append((v, None))
            continue
        s = json.loads(v["samenvatting"])
        if v["soort"] == "kort":
            g["kort"].append((v, s))
        elif v["rubriek"] == "redmond":
            g["redmond"].append((v, s))
        else:
            g[OORDEEL_REEKS.get(s.get("oordeel"), "lezen")].append((v, s))
    for k in ("kijken", "lezen", "overslaan"):
        g[k].sort(key=_sleutel)
    teveel, g["kijken"] = g["kijken"][config.MAX_KIJKEN:], g["kijken"][:config.MAX_KIJKEN]
    g["lezen"] = sorted(teveel + g["lezen"], key=_sleutel)
    g["kort"].sort(key=lambda vs: (not vs[1]["bruikbaar"], vs[0]["voorrang"], vs[0]["positie"]))
    bruikbaar = [vs for vs in g["kort"] if vs[1]["bruikbaar"]]
    g["kort_rest"] = len(g["kort"]) - min(len(bruikbaar), config.MAX_KORT)
    g["kort"] = bruikbaar[:config.MAX_KORT]
    return g


def onderwerp(nummer: int, g: dict) -> str:
    n = sum(len(g[k]) for k, _, _ in SECTIES) + len(g["geen"])
    k = len(g["kijken"])
    tip = f", {k} om te kijken" if k else ", niets verplichts"
    return f"{config.BRIEF_NAAM} {nummer}: {n} video's{tip}"


# ---------- platte tekst ----------

def tekst_body(nummer: int, datum: date, g: dict, intro: str = "") -> str:
    r = [f"{config.BRIEF_NAAM} {nummer}, {datum_nl(datum)}", ""]
    if intro:
        r += ["DEZE WEEK", intro, ""]
    for k, naam, _ in SECTIES:
        if not g[k]:
            continue
        r += [naam.upper(), ""]
        for v, s in g[k]:
            if k == "kort":
                r += [f"* {v['kanaal']}: {s['tip']}", f"  {yt(v['id'], kort=True)}"]
                continue
            r += [f"* {s['kop']}", f"  {v['kanaal']}, {minuten(v['duur_s'])}: {v['titel']}"]
            if k == "overslaan":
                r.append(f"  {s['waarom']}")
            else:
                r.append(f"  {s['lead']}")
                if k == "kijken" and s.get("context"):
                    r.append(f"  {s['context']}")
                r += ["  " + ("Nieuw:" if k == "redmond" else "De details:")] + [f"  - {i}" for i in s["inzichten"]]
                if k == "kijken":
                    if voor(s):
                        r.append(f"  Voor jou: {voor(s)}")
                    r += [f"  {mmss(m['sec'])} {m['wat']}: {yt(v['id'], m['sec'])}" for m in s["momenten"]]
            r += [f"  {yt(v['id'])}", ""]
        if k == "kort" and g["kort_rest"]:
            r += [f"  (en nog {g['kort_rest']} {'short' if g['kort_rest'] == 1 else 'shorts'} zonder bruikbare tip)", ""]
    if g["geen"]:
        r += ["NOG ZONDER ONDERTITELS", ""] + [f"* {v['kanaal']}: {v['titel']}: {yt(v['id'])}" for v, _ in g["geen"]] + [""]
    return "\n".join(r)


# ---------- html: bouwstenen ----------

def _a(href: str, inhoud: str, kleur: str = DONKERBLAUW, extra: str = "") -> str:
    return f'<a href="{e(href)}" style="color:{kleur};text-decoration:none;{extra}">{inhoud}</a>'


def _tegel(inhoud: str, padding: str = "14px 16px") -> str:
    """Een witte 'visual' op het grijze canvas."""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAPIER}" '
            f'style="background:{PAPIER};"><tr><td style="padding:{padding};">{inhoud}</td></tr></table>')


def kaart(waarde: str, label: str) -> str:
    return _tegel(f'<div style="font:600 24px/1.1 {SANS};color:{INKT};white-space:nowrap;">{e(waarde)}</div>'
                  f'<div style="font:12px/1.4 {SANS};color:{ZACHT};margin-top:4px;">{e(label)}</div>', "14px 14px 12px")


def kaarten(g: dict) -> str:
    lang = [v for k in ("redmond", "kijken", "lezen", "overslaan") for v, _ in g[k]]
    n = len(lang) + len(g["kort"]) + len(g["geen"])
    kijk = sum(v["duur_s"] or 0 for v, _ in g["kijken"])
    cel = lambda x, rechts: f'<td width="33%" valign="top" style="padding:0 {8 if rechts else 0}px 0 0;">{x}</td>'
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'{cel(kaart(str(n), "nieuwe video" + ("\'s" if n != 1 else "")), True)}'
            f'{cel(kaart(uren_kort(sum(v["duur_s"] or 0 for v in lang)), "kijktijd lange video's"), True)}'
            f'{cel(kaart(uren_kort(kijk) if kijk else "0", "kijktijd van de kijktips"), False)}'
            f'</tr></table>')


def per_kanaal(g: dict) -> list[tuple[str, dict]]:
    """[(kanaal, {reeks: seconden})] op totale tijd, grootste eerst. Shorts tellen hun echte duur."""
    tel: dict[str, dict] = {}
    for k in ("redmond", "kijken", "lezen", "overslaan", "kort"):
        for v, _ in g[k]:
            tel.setdefault(v["kanaal"], {})
            tel[v["kanaal"]][k] = tel[v["kanaal"]].get(k, 0) + max(v["duur_s"] or 45, 30)
    return sorted(tel.items(), key=lambda kv: -sum(kv[1].values()))


def staafgrafiek(g: dict) -> str:
    rijen = per_kanaal(g)
    if not rijen:
        return ""
    hoogste = max(sum(r.values()) for _, r in rijen)
    legenda = " ".join(
        f'<span style="display:inline-block;margin:0 12px 4px 0;font:11px/1.4 {SANS};color:{ZACHT};white-space:nowrap;">'
        f'<span style="display:inline-block;width:9px;height:9px;background:{REEKS[k]};vertical-align:-1px;margin-right:5px;"></span>'
        f'{REEKS_NAAM[k]}</span>'
        for k in ("redmond", "kijken", "lezen", "overslaan", "kort") if any(k in r for _, r in rijen))
    html_rijen = []
    for kanaal, r in rijen:
        totaal = sum(r.values())
        breedte = max(2, round(70 * totaal / hoogste))
        cellen = "".join(
            f'<td width="{max(1, round(100 * r[k] / totaal))}%" bgcolor="{REEKS[k]}" style="background:{REEKS[k]};height:14px;font-size:0;">&nbsp;</td>'
            for k in ("redmond", "kijken", "lezen", "overslaan", "kort") if k in r)
        html_rijen.append(
            f'<tr><td width="34%" valign="middle" style="padding:4px 10px 4px 0;font:12px/1.3 {SANS};color:{INKT};">{e(kanaal)}</td>'
            f'<td style="padding:4px 0;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
            f'<td width="{breedte}%"><table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="table-layout:fixed;"><tr>{cellen}</tr></table></td>'
            f'<td style="padding-left:6px;font:11px/1 {SANS};color:{ZACHT};white-space:nowrap;">{uren(totaal)}</td>'
            f'</tr></table></td></tr>')
    return _tegel(f'<div style="font:600 14px/1.3 {SANS};color:{INKT};">Kijktijd per kanaal</div>'
                  f'<div style="margin:8px 0 4px;">{legenda}</div>'
                  f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{"".join(html_rijen)}</table>')


def tijdbalk(v, s) -> str:
    duur = max(v["duur_s"] or 1, 1)
    punten = sorted({min(99, max(0, round(100 * m["sec"] / duur))) for m in s["momenten"]})
    cellen, vorige = [], 0
    for p in punten:
        if p > vorige:
            cellen.append(f'<td width="{p - vorige}%" bgcolor="{LIJN}" style="background:{LIJN};height:6px;font-size:0;">&nbsp;</td>')
        cellen.append(f'<td width="1%" bgcolor="{GEEL}" style="background:{GEEL};height:6px;font-size:0;">&nbsp;</td>')
        vorige = p + 1
    if vorige < 100:
        cellen.append(f'<td width="{100 - vorige}%" bgcolor="{LIJN}" style="background:{LIJN};height:6px;font-size:0;">&nbsp;</td>')
    balk = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="table-layout:fixed;margin-top:16px;"><tr>{"".join(cellen)}</tr></table>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="font:11px/1.6 {SANS};color:{ZACHT};">0:00</td>'
            f'<td align="right" style="font:11px/1.6 {SANS};color:{ZACHT};">{mmss(duur)}</td></tr></table>')
    rijen = "".join(
        f'<tr><td valign="top" width="52" style="padding:3px 0;font:600 13px/1.45 {SANS};">'
        f'{_a(yt(v["id"], m["sec"]), mmss(m["sec"]))}</td>'
        f'<td style="padding:3px 0;font:13px/1.45 {SANS};color:{INKT};">{e(m["wat"])}</td></tr>' for m in s["momenten"])
    return balk + (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:4px;">{rijen}</table>' if rijen else "")


def _meta(v, s) -> str:
    labels = ", ".join(s.get("labels", []))
    regel = ", ".join(x for x in [v["kanaal"], minuten(v["duur_s"])] if x)
    return (f'<div style="font:13px/1.5 {SANS};color:{ZACHT};margin-top:4px;">'
            f'<span style="color:{DONKERBLAUW};">{e(labels)}</span>{" / " if labels else ""}{e(regel)}</div>'
            f'<div style="font:12px/1.5 {SANS};color:{ZACHT};">{e(v["titel"])}</div>')


def _lijst(kop: str, items: list[str]) -> str:
    if not items:
        return ""
    li = "".join(f'<li style="margin:0 0 5px;">{e(i)}</li>' for i in items)
    return (f'<div style="font:600 13px/1 {SANS};color:{INKT};margin-top:14px;">{kop}</div>'
            f'<ul style="font:14px/1.5 {SANS};color:{INKT};margin:8px 0 0;padding-left:18px;">{li}</ul>')


def _features(items: list[str]) -> str:
    """Maandupdate als tabelvisual: feature | wat het doet."""
    rijen = []
    for i in items:
        naam, _, wat = i.partition(":")
        if not wat:
            naam, wat = "", i
        rijen.append(f'<tr><td valign="top" width="38%" style="padding:7px 10px 7px 0;border-top:1px solid {LIJN};'
                     f'font:600 13px/1.4 {SANS};color:{INKT};">{e(naam.strip())}</td>'
                     f'<td valign="top" style="padding:7px 0;border-top:1px solid {LIJN};font:13px/1.45 {SANS};color:{INKT};">'
                     f'{e(wat.strip())}</td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:12px;">'
            f'<tr><td style="padding:0 0 6px;font:600 12px/1 {SANS};color:{ZACHT};">Feature</td>'
            f'<td style="padding:0 0 6px;font:600 12px/1 {SANS};color:{ZACHT};">Wat het doet</td></tr>{"".join(rijen)}</table>')


def _kop(v, s, maat: int) -> str:
    return (f'<div style="font:600 {maat}px/1.25 {SANS};color:{INKT};">{_a(yt(v["id"]), e(s["kop"]), INKT)}</div>')


def item_redmond(v, s) -> str:
    return (f'<tr><td style="padding:22px 0;border-top:1px solid {LIJN};">{_kop(v, s, 19)}{_meta(v, s)}'
            f'<div style="font:15px/1.6 {SANS};color:{INKT};margin-top:10px;">{e(s["lead"])}</div>'
            f'{_features(s["inzichten"])}</td></tr>')


def item_kijken(v, s) -> str:
    band = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">'
            f'<tr><td bgcolor="{GEEL_BLEEK}" style="background:{GEEL_BLEEK};border-left:4px solid {GEEL};padding:10px 14px;'
            f'font:14px/1.5 {SANS};color:{INKT};"><b>Voor jou.</b> {e(voor(s))}</td></tr></table>') if voor(s) else ""
    context = f'<div style="font:15px/1.6 {SANS};color:{ZACHT};margin-top:8px;">{e(s["context"])}</div>' if s.get("context") else ""
    return (f'<tr><td style="padding:26px 0 28px;border-top:1px solid {LIJN};">{_kop(v, s, 21)}{_meta(v, s)}'
            f'<div style="font:16px/1.6 {SANS};color:{INKT};margin-top:12px;">{e(s["lead"])}</div>{context}'
            f'{_lijst("De details", s["inzichten"])}{band}{tijdbalk(v, s)}</td></tr>')


def item_lezen(v, s) -> str:
    return (f'<tr><td style="padding:20px 0;border-top:1px solid {LIJN};">{_kop(v, s, 17)}{_meta(v, s)}'
            f'<div style="font:15px/1.6 {SANS};color:{INKT};margin-top:10px;">{e(s["lead"])}</div>'
            f'{_lijst("De details", s["inzichten"])}</td></tr>')


def item_overslaan(v, s) -> str:
    return (f'<tr><td style="padding:11px 0;border-top:1px solid {LIJN};font:14px/1.5 {SANS};color:{INKT};">'
            f'{_a(yt(v["id"]), e(s["kop"]), INKT, "font-weight:600;")}'
            f'<span style="color:{ZACHT};"> ({e(v["kanaal"])}). {e(s["waarom"])}</span></td></tr>')


def tabel_kort(g: dict) -> str:
    rijen = "".join(
        f'<tr><td valign="top" width="30%" style="padding:8px 10px 8px 0;border-top:1px solid {LIJN};'
        f'font:13px/1.4 {SANS};color:{ZACHT};">{e(v["kanaal"])}</td>'
        f'<td valign="top" style="padding:8px 0;border-top:1px solid {LIJN};font:14px/1.45 {SANS};color:{INKT};">'
        f'{_a(yt(v["id"], kort=True), e(s["tip"]), INKT)}</td></tr>' for v, s in g["kort"])
    rest = (f'<tr><td colspan="2" style="padding:8px 0;border-top:1px solid {LIJN};font:12px/1.4 {SANS};color:{ZACHT};">'
            f'En nog {g["kort_rest"]} {"short" if g["kort_rest"] == 1 else "shorts"} zonder bruikbare tip.</td></tr>') if g["kort_rest"] else ""
    return (f'<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td style="padding:0 0 6px;font:600 12px/1 {SANS};color:{ZACHT};">Kanaal</td>'
            f'<td style="padding:0 0 6px;font:600 12px/1 {SANS};color:{ZACHT};">Tip</td></tr>{rijen}{rest}</table></td></tr>')


def sectiekop(naam: str, uitleg: str, n: int) -> str:
    return (f'<tr><td style="padding:38px 0 12px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td bgcolor="{GEEL}" width="5" style="background:{GEEL};width:5px;font-size:0;">&nbsp;</td>'
            f'<td style="padding-left:10px;font:600 22px/1.2 {SANS};color:{INKT};">{e(naam)} '
            f'<span style="font-weight:400;color:{ZACHT};font-size:18px;">{n}</span></td></tr></table>'
            f'<div style="font:14px/1.5 {SANS};color:{ZACHT};margin-top:6px;">{uitleg}</div></td></tr>')


def html_body(nummer: int, datum: date, g: dict, intro: str = "") -> str:
    maak = {"redmond": item_redmond, "kijken": item_kijken, "lezen": item_lezen, "overslaan": item_overslaan}
    blokken = []
    for k, naam, uitleg in SECTIES:
        if not g[k]:
            continue
        blokken.append(sectiekop(naam, uitleg, len(g[k])))
        blokken += [tabel_kort(g)] if k == "kort" else [maak[k](v, s) for v, s in g[k]]
    if g["geen"]:
        blokken.append(f'<tr><td style="padding:34px 0 8px;font:600 16px/1.3 {SANS};color:{ZACHT};">Nog zonder ondertitels</td></tr>')
        blokken += [f'<tr><td style="padding:8px 0;border-top:1px solid {LIJN};font:14px/1.5 {SANS};">'
                    f'{_a(yt(v["id"]), e(v["kanaal"] + ": " + v["titel"]), INKT)}</td></tr>' for v, _ in g["geen"]]
    n_kanalen = len(per_kanaal(g))
    intro_html = (f'<tr><td style="padding:22px 30px 0;font:17px/1.6 {SANS};color:{INKT};">{e(intro)}</td></tr>' if intro else "")
    return f"""<!doctype html><html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light only">
<title>{e(config.BRIEF_NAAM)} {nummer}</title></head>
<body style="margin:0;padding:0;background:{CANVAS};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{CANVAS}" style="background:{CANVAS};">
<tr><td align="center" style="padding:24px 10px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAPIER}" style="width:100%;max-width:640px;background:{PAPIER};">
<tr><td bgcolor="{GEEL}" style="background:{GEEL};height:6px;font-size:0;line-height:6px;">&nbsp;</td></tr>
<tr><td style="padding:22px 30px 18px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
    <td valign="bottom" style="font:700 28px/1 {SANS};color:{INKT};letter-spacing:-0.5px;">{e(config.BRIEF_NAAM)}</td>
    <td valign="bottom" align="right" style="font:13px/1.35 {SANS};color:{ZACHT};">nummer {nummer}<br>{datum_nl(datum)}</td>
  </tr></table>
  <div style="font:14px/1.5 {SANS};color:{ZACHT};margin-top:6px;">Wat er deze week verscheen op {n_kanalen} Power BI- en Fabric-kanalen.</div>
</td></tr>
<tr><td bgcolor="{CANVAS}" style="background:{CANVAS};padding:12px;">
  {kaarten(g)}
  <div style="height:8px;font-size:0;line-height:8px;">&nbsp;</div>
  {staafgrafiek(g)}
</td></tr>
{intro_html}
<tr><td style="padding:0 30px 10px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{''.join(blokken)}</table></td></tr>
<tr><td style="padding:24px 30px 28px;border-top:1px solid {LIJN};font:12px/1.6 {SANS};color:{ZACHT};">
  {e(config.BRIEF_NAAM)} {nummer}, {datum_nl(datum)}. Geschreven door een taalmodel uit de automatische
  YouTube-ondertitels, dus details kunnen afwijken: de links brengen je naar de bron.</td></tr>
</table></td></tr></table></body></html>"""


def verstuur(nummer: int, datum: date, g: dict, intro: str = "", client: httpx.Client | None = None) -> bool:
    token, van, aan = (os.environ.get(k, "") for k in ("POSTMARK_TOKEN", "MAIL_FROM", "MAIL_TO"))
    if not (token and van and aan):
        log.warning("POSTMARK_TOKEN/MAIL_FROM/MAIL_TO ontbreken; geen mail")
        return False
    if "<" not in van:
        van = f"{config.BRIEF_NAAM} <{van}>"
    client = client or httpx.Client(timeout=20)
    bericht = {"From": van, "To": aan, "Subject": onderwerp(nummer, g),
               "TextBody": tekst_body(nummer, datum, g, intro), "HtmlBody": html_body(nummer, datum, g, intro),
               "MessageStream": "outbound", "TrackOpens": False, "TrackLinks": "None"}
    try:
        r = client.post("https://api.postmarkapp.com/email", json=bericht,
                        headers={"X-Postmark-Server-Token": token, "Accept": "application/json"})
        if not 200 <= r.status_code < 300:
            log.warning("postmark: HTTP %s %s", r.status_code, r.text[:200])
        return 200 <= r.status_code < 300
    except httpx.HTTPError as ex:
        log.warning("postmark: %s", ex)
        return False
