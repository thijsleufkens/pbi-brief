from datetime import date

import pytest

from pbibrief import bron, cli, config, db, mail, samenvat


def lijst(*items):
    return bron.parse_lijst({"entries": [{"id": i, "title": t, "duration": d} for i, t, d in items]})


KANAAL = {"naam": "SQLBI", "url": "https://x", "shorts": True}
REDMOND = {"naam": "Microsoft Power BI", "url": "https://y", "rubriek": "redmond"}


def test_eerste_run_per_kanaal_en_daarna_alles(tmp_path):
    con = db.open_db(tmp_path / "t.db")
    lang = lijst(("L1", "Nieuw", 900), ("L2", "Ouder", 800), ("C1", "Clip op videos-tab", 50), ("P", "Premiere", None))
    kort = lijst(("K1", "short", None), ("K2", "oudere short", None))
    assert cli.ontdek_kanaal(con, KANAAL, 0, lang, kort) == 2          # L1 + K1
    rijen = {r["id"]: (r["soort"], r["status"]) for r in con.execute("SELECT * FROM video")}
    assert rijen == {"L1": ("lang", "nieuw"), "L2": ("lang", "genegeerd"), "K1": ("kort", "nieuw"),
                     "K2": ("kort", "genegeerd"), "C1": ("kort", "genegeerd")}
    assert cli.ontdek_kanaal(con, KANAAL, 0, lijst(("L3", "x", 600)) + lang, kort) == 1


def test_redmond_alleen_bij_update_titel(tmp_path):
    con = db.open_db(tmp_path / "t.db")
    cli.ontdek_kanaal(con, REDMOND, 1, lijst(("U", "Power BI Update - November 2026", 700)), [])
    cli.ontdek_kanaal(con, REDMOND, 1, lijst(("A", "Copilot deep dive", 900)), [])
    assert dict(con.execute("SELECT id, rubriek FROM video").fetchall()) == {"U": "redmond", "A": ""}


def test_te_doen_lang_voor_kort_dan_voorrang(tmp_path):
    con = db.open_db(tmp_path / "t.db")
    db.voeg_toe(con, "K0", "k", "A", "kort", voorrang=0)
    db.voeg_toe(con, "L5", "l", "B", "lang", voorrang=5)
    db.voeg_toe(con, "L1", "l", "C", "lang", voorrang=1)
    assert [r["id"] for r in db.te_doen(con)] == ["L1", "L5", "K0"]


def test_ontdek_slaat_kapot_kanaal_over(monkeypatch, tmp_path):
    con = db.open_db(tmp_path / "t.db")
    monkeypatch.setattr(config, "kanalen", lambda: [{"naam": "Kapot", "url": "https://kapot"}, {"naam": "Goed", "url": "https://goed"}])
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    def haal(url, n):
        if "kapot" in url:
            raise RuntimeError("404")
        return lijst(("G", "goed", 900))
    monkeypatch.setattr(bron, "haal_lijst", haal)
    assert cli.ontdek(con) == 1
    monkeypatch.setattr(config, "kanalen", lambda: [{"naam": "Kapot", "url": "https://kapot"}])
    with pytest.raises(RuntimeError):
        cli.ontdek(con)


def _lang(oordeel, score, kop="Kop <b>"):
    return {"kop": kop, "lead": "Lead.", "context": "Ctx.", "labels": ["DAX"], "inzichten": ["i1", "Feature: doet x"],
            "voor_lezer": "iets", "oordeel": oordeel, "waarom": "omdat", "score": score,
            "momenten": [{"sec": 75, "wat": "demo"}]}


def _vul(con):
    for vid, oordeel, score in [("A", "kijken", 3), ("B", "kijken", 5), ("C", "kijken", 4), ("D", "kijken", 4),
                                ("E", "overslaan", 1)]:
        db.voeg_toe(con, vid, f"Video {vid}", "SQLBI", "lang")
        db.markeer_klaar(con, vid, _lang(oordeel, score), 1200, 3000)
    db.voeg_toe(con, "U", "Power BI Update", "Microsoft Power BI", "lang", "redmond", 1)
    db.markeer_klaar(con, "U", _lang("samenvatting volstaat", 3), 900, 2000)
    for i in range(10):
        db.voeg_toe(con, f"K{i}", f"short {i}", "Goodly", "kort", voorrang=6, positie=i)
        db.markeer_klaar(con, f"K{i}", {"tip": f"Tip {i}", "label": "DAX", "bruikbaar": i != 3}, 40, 100)
    db.voeg_toe(con, "G", "zonder", "Fernan", "lang")
    for _ in range(5):
        db.markeer_mislukt(con, "G", "x", 5)
    db.voeg_toe(con, "KG", "short zonder", "Goodly", "kort")
    for _ in range(5):
        db.markeer_mislukt(con, "KG", "x", 5)


def test_groepering(tmp_path):
    con = db.open_db(tmp_path / "t.db")
    _vul(con)
    g = mail.groepeer(db.voor_editie(con))
    assert [v["id"] for v, _ in g["kijken"]] == ["B", "C", "D"]
    assert [v["id"] for v, _ in g["lezen"]] == ["A"]
    assert [v["id"] for v, _ in g["redmond"]] == ["U"]
    assert len(g["kort"]) == 8 and "K3" not in [v["id"] for v, _ in g["kort"]] and g["kort_rest"] == 2
    assert [v["id"] for v, _ in g["geen"]] == ["G"]                     # shorts zonder transcript vallen weg
    assert mail.onderwerp(1, g) == "PBI-brief 1: 15 video's, 3 om te kijken"


def test_html_en_tekst(tmp_path):
    con = db.open_db(tmp_path / "t.db")
    _vul(con)
    g = mail.groepeer(db.voor_editie(con))
    h = mail.html_body(1, date(2026, 11, 22), g, intro="Thema <x>.")
    for stuk in ["Thema &lt;x&gt;.", "Kop &lt;b&gt;", "Uit Redmond", "Kort &amp; handig", "Kijktijd per kanaal",
                 "En nog 2 shorts", "watch?v=B&amp;t=75s", "youtube.com/shorts/K0", ">Feature<", "doet x"]:
        assert stuk in h, stuk
    t = mail.tekst_body(1, date(2026, 11, 22), g, "Intro")
    assert "UIT REDMOND" in t and "KORT & HANDIG" in t and "Goodly: Tip 0" in t and "NOG ZONDER ONDERTITELS" in t


def test_staafgrafiek_grootste_kanaal_eerst(tmp_path):
    con = db.open_db(tmp_path / "t.db")
    _vul(con)
    rijen = mail.per_kanaal(mail.groepeer(db.voor_editie(con)))
    assert rijen[0][0] == "SQLBI" and set(rijen[0][1]) == {"kijken", "lezen", "overslaan"}


def test_schoon_redmond_tot_acht():
    s = samenvat.schoon({"inzichten": [str(i) for i in range(12)], "labels": ["DAX", "onzin"]}, 60, max_inzichten=8)
    assert len(s["inzichten"]) == 8 and s["labels"] == ["DAX"]


def test_bouw_tekst_en_mmss():
    t = bron.bouw_tekst([(0, 2, "hello"), (61, 3, "next\nblock")], blok_s=60)
    assert t.tekst.splitlines() == ["[00:00] hello", "[01:01] next block"] and bron.mmss(3725) == "1:02:05"


def test_kanalen_yaml_laadt_alleen_actieve():
    namen = [k["naam"] for k in config.kanalen()]
    assert "SQLBI" in namen and "RADACAD" not in namen and len(namen) == 11


def test_prompts_hebben_lezer():
    assert "Over de lezer" in samenvat.systeemprompt()


def test_wachtrij_en_lever(tmp_path):
    import json
    from pbibrief import extern
    con = db.open_db(tmp_path / "x.db")
    for vid in ("A", "B", "C", "D"):
        db.voeg_toe(con, vid, "t", "K")
    db.bewaar_transcript(con, "D", "[00:00] al binnen", 60, 2, False)
    assert [v["id"] for v in extern.wachtrij(con, 2)] == ["A", "B"]
    regels = [json.dumps({"id": "A", "snippets": [[0, 2, "hallo daar"], [61, 3, "verder"]]}),
              json.dumps({"id": "B", "geen": "NoTranscriptFound"}),
              json.dumps({"id": "ONBEKEND", "snippets": [[0, 1, "x"]]}),
              json.dumps({"id": "D", "snippets": [[0, 1, "overschrijft niet"]]}),
              json.dumps({"klaar": True})]
    assert extern.lever(con, regels) == (1, 1, "klaar")
    rij = {r["id"]: r for r in con.execute("SELECT * FROM video")}
    assert rij["A"]["transcript"].startswith("[00:00] hallo daar") and rij["A"]["duur_s"] == 64
    assert rij["B"]["pogingen"] == 1 and rij["B"]["transcript"] is None
    assert rij["D"]["transcript"] == "[00:00] al binnen"
    assert extern.lever(con, [json.dumps({"id": "C", "snippets": [[0, 1, "x"]]})])[2] == "onvolledig"
    assert extern.lever(con, [json.dumps({"geblokkeerd": True})])[2] == "geblokkeerd"


def test_nacht_extern_haalt_zelf_niets(tmp_path, monkeypatch):
    from pbibrief import cli
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "x.db")
    monkeypatch.setattr(config, "TRANSCRIPTEN", "extern")
    monkeypatch.setattr(config, "HEARTBEAT_DIR", "")
    monkeypatch.setattr(cli, "ontdek", lambda *a: 0)
    monkeypatch.setattr(bron, "haal_lijst", lambda *a: [])
    monkeypatch.setattr(bron, "haal_transcript", lambda vid: (_ for _ in ()).throw(AssertionError("niet ophalen")))
    monkeypatch.setattr(cli, "Qwen", lambda: None)
    con = db.open_db(config.DB_PATH)
    db.voeg_toe(con, "A", "t", "K")
    assert cli.nacht() == 0
    assert con.execute("SELECT status FROM video WHERE id='A'").fetchone()[0] == "nieuw"
