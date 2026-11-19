"""Instellingen uit de omgeving (op de VPS via EnvironmentFile=.env) en kanalen.yaml."""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PBI_DATA", ROOT / "data"))
DB_PATH = Path(os.environ.get("PBI_DB", DATA_DIR / "pbi-brief.db"))
KANALEN_PAD = Path(os.environ.get("PBI_KANALEN", ROOT / "kanalen.yaml"))

LIJST_LANG = 10               # nieuwste video's per kanaal per nacht
LIJST_KORT = 6                # nieuwste shorts per kanaal per nacht
MIN_DUUR_S = 240              # korter dan dit op de /videos-tab telt als kort

# OpenAI-compatibel endpoint. Geen fallback: een vergeten env-var moet falen.
QWEN_BASE_URL = os.environ.get("QWEN_BASE_URL", "")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "Qwen3.8-Flash-Next")
VERBODEN_LLM_HOST = os.environ.get("QWEN_VERBODEN_HOST", "")

POSTGRAM_URL = os.environ.get("POSTGRAM_URL", "http://127.0.0.1:3100").rstrip("/")
POSTGRAM_KEY = os.environ.get("POSTGRAM_KEY", "")

HEARTBEAT_DIR = os.environ.get("HEARTBEAT_DIR", "")
_EIGEN_LEZER = ROOT / "prompts" / "lezer.md"
LEZER_PAD = Path(os.environ.get("PBI_LEZER") or (_EIGEN_LEZER if _EIGEN_LEZER.exists() else ROOT / "prompts" / "lezer.voorbeeld.md"))
BRIEF_NAAM = os.environ.get("PBI_NAAM", "PBI-brief")

MAX_WOORDEN = 45_000
MAX_POGINGEN = 5              # nachten zonder transcript voordat we opgeven
EERSTE_RUN_LANG = 1           # eerste run: per kanaal alleen de nieuwste lange video ...
EERSTE_RUN_KORT = 1           # ... en de nieuwste short; de rest genegeerd
BLOK_SECONDEN = 60
PAUZE_S = float(os.environ.get("PBI_PAUZE_S", "20"))          # tussen transcripten (rate-limit)
NACHTBUDGET = int(os.environ.get("PBI_NACHTBUDGET", "12"))    # max nieuwe transcripten per nacht
MAX_KIJKEN = 3
MAX_KORT = 8


def kanalen() -> list[dict]:
    with open(KANALEN_PAD, encoding="utf-8") as f:
        alle = yaml.safe_load(f)["kanalen"]
    return [k for k in alle if k.get("actief", True)]
