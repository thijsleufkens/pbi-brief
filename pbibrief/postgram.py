"""Optioneel: één memory per editie in Postgram (work). Zonder POSTGRAM_KEY: niets."""
import logging

import httpx

from . import config

log = logging.getLogger("pbibrief.postgram")


def bewaar_editie(tekst: str, nummer: int, client: httpx.Client | None = None) -> bool:
    if not config.POSTGRAM_KEY:
        return False
    client = client or httpx.Client(timeout=120)
    try:
        r = client.post(f"{config.POSTGRAM_URL}/api/entities",
                        headers={"Authorization": f"Bearer {config.POSTGRAM_KEY}", "User-Agent": "pbi-brief/1.0"},
                        json={"type": "memory", "content": tekst, "visibility": "work",
                              "tags": ["power-bi", "pbi-brief", "nieuwsbrief"],
                              "metadata": {"bron": "pbi-brief", "editie": nummer}})
        r.raise_for_status()
        return True
    except httpx.HTTPError as e:
        log.warning("postgram: %s", e)
        return False
