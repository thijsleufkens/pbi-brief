"""De opening van de editie: één Qwen-aanroep over de samenvattingen (niet de transcripten).
De kijktips kiezen we zelf uit de oordelen; Qwen schrijft alleen de verbindende tekst."""
import logging

from . import config
from .qwen import Qwen, QwenFout

log = logging.getLogger("pbibrief.week")

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["intro"],
          "properties": {"intro": {"type": "string"}}}


def invoer(items: list[tuple[str, dict]]) -> str:
    """items = [("kanaal: titel", samenvatting)]"""
    return "\n\n".join(f"- {t}\n  Kop: {s['kop']}\n  Lead: {s.get('lead') or s.get('kern', '')}\n"
                       f"  Labels: {', '.join(s.get('labels', []))}" for t, s in items)


def schrijf_intro(items: list[tuple[str, dict]], qwen: Qwen | None = None) -> str:
    """Lege string als het niet lukt: de mail gaat dan zonder opening."""
    if len(items) < 2:
        return ""
    try:
        qwen = qwen or Qwen()
        prompt = ((config.ROOT / "prompts" / "week.md").read_text(encoding="utf-8") + "\n\n"
                  + config.LEZER_PAD.read_text(encoding="utf-8"))
        obj, _ = qwen.chat_json([{"role": "system", "content": prompt},
                                 {"role": "user", "content": invoer(items)}],
                                SCHEMA, naam="week", max_tokens=500, temperatuur=0.3)
        return obj.get("intro", "").strip()
    except (QwenFout, OSError) as e:
        log.warning("week-intro mislukt, mail zonder opening: %s", e)
        return ""
