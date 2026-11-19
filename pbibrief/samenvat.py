"""Eén video samenvatten met het taalmodel: lang als nieuwsbericht, kort als één tip."""
from . import config
from .qwen import Qwen

OORDELEN = ["kijken", "samenvatting volstaat", "overslaan"]
LABELS = ["DAX", "Power Query", "datamodel", "visuals & rapportage", "Fabric & data-engineering",
          "AI & Copilot", "beheer & governance", "embedded & delen", "Excel", "overig"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kop", "lead", "context", "labels", "inzichten", "voor_lezer", "oordeel", "waarom", "score", "momenten"],
    "properties": {
        "kop": {"type": "string"},
        "lead": {"type": "string"},
        "context": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string", "enum": LABELS}},
        "inzichten": {"type": "array", "items": {"type": "string"}},
        "voor_lezer": {"type": "string"},
        "oordeel": {"type": "string", "enum": OORDELEN},
        "waarom": {"type": "string"},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "momenten": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["sec", "wat"],
            "properties": {"sec": {"type": "integer"}, "wat": {"type": "string"}}}},
    },
}


def systeemprompt() -> str:
    return ((config.ROOT / "prompts" / "samenvatting.md").read_text(encoding="utf-8") + "\n\n"
            + config.LEZER_PAD.read_text(encoding="utf-8"))


def berichten(titel: str, transcript: str, afgekapt: bool, kanaal: str = "") -> list[dict]:
    noot = "\n(Het transcript is afgekapt; vat samen wat er staat.)" if afgekapt else ""
    return [
        {"role": "system", "content": systeemprompt()},
        {"role": "user", "content": f"Kanaal: {kanaal}\nTitel: {titel}{noot}\n\nTranscript:\n{transcript}"},
    ]


def schoon(obj: dict, duur_s: int, max_inzichten: int = 5) -> dict:
    """Vangnet voor wat het schema niet afdwingt (aantallen, tijdstempels binnen de video)."""
    obj["inzichten"] = [i.strip() for i in obj.get("inzichten", []) if i.strip()][:max_inzichten]
    labels = [l for l in obj.get("labels", []) if l in LABELS]
    obj["labels"] = list(dict.fromkeys(labels))[:2] or ["overig"]
    obj["score"] = min(5, max(1, int(obj.get("score", 3))))
    if obj.get("oordeel") not in OORDELEN:
        obj["oordeel"] = "samenvatting volstaat"
    momenten = []
    for m in obj.get("momenten", []):
        sec = int(m.get("sec", -1))
        if 0 <= sec <= max(duur_s, 0) and m.get("wat", "").strip():
            momenten.append({"sec": sec, "wat": m["wat"].strip()})
    obj["momenten"] = sorted(momenten, key=lambda m: m["sec"])[:4]
    return obj


def vat_samen(qwen: Qwen, titel: str, transcript: str, duur_s: int, afgekapt: bool,
              kanaal: str = "", redmond: bool = False) -> tuple[dict, dict]:
    obj, meta = qwen.chat_json(berichten(titel, transcript, afgekapt, kanaal), SCHEMA, naam="video",
                               max_tokens=1800 if redmond else 1500, temperatuur=0.2)
    return schoon(obj, duur_s, max_inzichten=8 if redmond else 5), meta


KORT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["tip", "label", "bruikbaar"],
    "properties": {"tip": {"type": "string"}, "label": {"type": "string", "enum": LABELS},
                   "bruikbaar": {"type": "boolean"}},
}


def vat_kort_samen(qwen: Qwen, titel: str, transcript: str, kanaal: str = "") -> tuple[dict, dict]:
    prompt = ((config.ROOT / "prompts" / "kort.md").read_text(encoding="utf-8") + "\n\n"
              + config.LEZER_PAD.read_text(encoding="utf-8"))
    obj, meta = qwen.chat_json([{"role": "system", "content": prompt},
                                {"role": "user", "content": f"Kanaal: {kanaal}\nTitel: {titel}\n\nTranscript:\n{transcript}"}],
                               KORT_SCHEMA, naam="short", max_tokens=200, temperatuur=0.2)
    obj["tip"] = " ".join(obj.get("tip", "").split())
    if obj.get("label") not in LABELS:
        obj["label"] = "overig"
    obj["bruikbaar"] = bool(obj.get("bruikbaar"))
    return obj, meta
