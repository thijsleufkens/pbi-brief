"""SQLite: video's en edities."""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS video (
  id TEXT PRIMARY KEY,
  titel TEXT NOT NULL,
  kanaal TEXT NOT NULL DEFAULT '',
  soort TEXT NOT NULL DEFAULT 'lang',     -- lang | kort
  rubriek TEXT NOT NULL DEFAULT '',       -- '' | redmond
  voorrang INTEGER NOT NULL DEFAULT 0,    -- plek van het kanaal in kanalen.yaml (0 = hoogst)
  positie INTEGER NOT NULL DEFAULT 0,     -- plek in de lijst bij ontdekken (0 = nieuwst)
  ontdekt TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL DEFAULT 'nieuw',   -- nieuw | klaar | geen_transcript | genegeerd
  pogingen INTEGER NOT NULL DEFAULT 0,
  laatste_fout TEXT,
  duur_s INTEGER,
  woorden INTEGER,
  samenvatting TEXT,                      -- JSON
  transcript TEXT,                        -- bewaard: opnieuw samenvatten haalt niet opnieuw op
  afgekapt INTEGER NOT NULL DEFAULT 0,
  editie_id INTEGER REFERENCES editie(id)
);
CREATE TABLE IF NOT EXISTS editie (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  datum TEXT NOT NULL,
  verstuurd INTEGER NOT NULL DEFAULT 0
);
"""


def open_db(pad: Path) -> sqlite3.Connection:
    pad.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(pad)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def kanaal_is_nieuw(con, kanaal: str) -> bool:
    return con.execute("SELECT COUNT(*) FROM video WHERE kanaal=?", (kanaal,)).fetchone()[0] == 0


def voeg_toe(con, vid: str, titel: str, kanaal: str = "", soort: str = "lang", rubriek: str = "",
             voorrang: int = 0, positie: int = 0, status: str = "nieuw", duur_s: int | None = None) -> bool:
    cur = con.execute("INSERT OR IGNORE INTO video (id, titel, kanaal, soort, rubriek, voorrang, positie, status, duur_s) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (vid, titel, kanaal, soort, rubriek, voorrang, positie, status, duur_s))
    con.commit()
    return cur.rowcount == 1


def te_doen(con) -> list[sqlite3.Row]:
    """Lang vóór kort, dan kanaalvoorrang, dan oudst ontdekt: zo valt bij een krap budget de
    minst belangrijke short af, niet de SQLBI-video."""
    return con.execute("SELECT * FROM video WHERE status='nieuw' "
                       "ORDER BY (soort='kort'), voorrang, ontdekt, positie").fetchall()


def bewaar_transcript(con, vid: str, tekst: str, duur_s: int, woorden: int, afgekapt: bool) -> None:
    con.execute("UPDATE video SET transcript=?, duur_s=?, woorden=?, afgekapt=? WHERE id=?",
                (tekst, duur_s, woorden, int(afgekapt), vid))
    con.commit()


def markeer_klaar(con, vid: str, samenvatting: dict, duur_s: int, woorden: int) -> None:
    con.execute("UPDATE video SET status='klaar', samenvatting=?, duur_s=?, woorden=?, laatste_fout=NULL "
                "WHERE id=?", (json.dumps(samenvatting, ensure_ascii=False), duur_s, woorden, vid))
    con.commit()


def markeer_mislukt(con, vid: str, fout: str, max_pogingen: int) -> None:
    con.execute("UPDATE video SET pogingen=pogingen+1, laatste_fout=? WHERE id=?", (fout[:500], vid))
    con.execute("UPDATE video SET status='geen_transcript' WHERE id=? AND pogingen>=?", (vid, max_pogingen))
    con.commit()


def voor_editie(con) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM video WHERE editie_id IS NULL AND status IN ('klaar','geen_transcript') "
                       "ORDER BY voorrang, ontdekt, positie").fetchall()


def leg_editie_vast(con, datum: str, ids: list[str]) -> int:
    cur = con.execute("INSERT INTO editie (datum, verstuurd) VALUES (?, 1)", (datum,))
    eid = cur.lastrowid
    con.executemany("UPDATE video SET editie_id=? WHERE id=?", [(eid, i) for i in ids])
    con.commit()
    return eid


def editienummer(con) -> int:
    return con.execute("SELECT COUNT(*) FROM editie").fetchone()[0] + 1
