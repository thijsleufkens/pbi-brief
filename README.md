# PBI-brief

Een wekelijkse verzamelmail van Power BI- en Microsoft Fabric-kanalen op YouTube. Elke nacht
haalt hij de nieuwe video's en shorts van een lijst kanalen op, leest de automatische
ondertitels en laat een **lokaal taalmodel** er een kort nieuwsbericht of een tip van maken.
Elke zondag één mail, opgemaakt als een Power BI-rapportpagina:

- drie kaarten (nieuwe video's, kijktijd, kijktijd van de kijktips) en een gestapelde
  staafgrafiek **kijktijd per kanaal**;
- **Uit Redmond**: de maandupdates van Power BI en Fabric als tabel met features;
- **Kijken** (hooguit 3), met een tijdbalk en links naar de interessante momenten;
- **Lezen volstaat**: kop, lead en de details;
- **Kort & handig**: shorts in één zin wat je ermee kunt (hooguit 8);
- **Overslaan**: in één zin waarom.

Zusje van [AIE-brief](https://github.com/thijsleufkens/aie-brief) (één kanaal, AI-engineering).

## Hoe het werkt

```
kanalen.yaml → yt-dlp (plat: /videos en /shorts per kanaal) → youtube-transcript-api
            → taalmodel (JSON-schema; lang = nieuwsbericht, short = één tip) → SQLite
            → zondag: opening + mail via Postmark
```

- **Kanalen** staan in `kanalen.yaml`, met volgorde als voorrang, `tier` (kern/optioneel),
  of shorts meedoen, en `rubriek: redmond` voor de officiële Microsoft-kanalen.
- **Nachtbudget.** YouTube geeft een IP na een paar dozijn transcripten in korte tijd een 429.
  Daarom haalt hij er hooguit 12 per nacht op (`PBI_NACHTBUDGET`), met 20 s pauze, lange
  video's vóór shorts, en bewaart hij elk transcript zodat opnieuw samenvatten niets ophaalt.
- **Nieuw kanaal**: alleen de nieuwste lange video en short gaan mee, de achterstand niet.
- **Een harde grens op kijktips**: een klein lokaal model is een goede schrijver en een slechte
  beoordelaar. De code laat er 3 door, op score. Shorts kiest de code op kanaalvolgorde; het
  model zegt alleen of er een bruikbare tip in zit.
- **De lens** is een tekstbestand: `prompts/lezer.voorbeeld.md`, of je eigen
  `prompts/lezer.md` (staat in `.gitignore`).

## Zelf draaien

Nodig: Python 3.12, een OpenAI-compatibel endpoint met `response_format: json_schema`
(bijvoorbeeld llama.cpp) en voor de mail een Postmark-token.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
export QWEN_BASE_URL=http://localhost:8080/v1
.venv/bin/python -m pbibrief.cli nacht            # ophalen + samenvatten
.venv/bin/python -m pbibrief.cli editie --droog   # mail als data/voorbeeld.html
```

| Variabele | Betekenis |
|---|---|
| `QWEN_BASE_URL`, `QWEN_MODEL` | endpoint en modelnaam |
| `PBI_KANALEN` | ander kanalenbestand dan `kanalen.yaml` |
| `PBI_NACHTBUDGET`, `PBI_PAUZE_S` | max transcripten per nacht, pauze ertussen |
| `PBI_NAAM`, `PBI_LEZER` | naam van de brief, pad naar je lens |
| `POSTMARK_TOKEN`, `MAIL_FROM`, `MAIL_TO` | verzending |
| `HEARTBEAT_DIR` | optioneel: heartbeat-bestand na elke geslaagde run |

Op een server: `deploy.sh` met een ingevuld `deploy.env` (zie `deploy.env.example`) plaatst
de code, maakt een venv en zet twee systemd-timers aan: nacht 01:30, zondag 08:10
(Europe/Amsterdam).

## Grenzen

- Samenvattingen komen uit automatische ondertitels plus een klein model: details kunnen
  afwijken. De links brengen je naar de bron.
- Een kanaal waarvan de lijst niet lukt, wordt die nacht overgeslagen; lukt geen enkele lijst,
  dan faalt de run zichtbaar (geen heartbeat).
- Kanalen in `kanalen.yaml` zijn in november 2026 gemeten op activiteit; dat verandert.

Licentie: 0BSD.
