"""Client voor een OpenAI-compatibel taalmodel (llama.cpp met Qwen of iets vergelijkbaars).

Strikt sequentieel: één aanroep tegelijk, nooit threads. Een proxy voor het model kan ons in
de rij zetten; daarna kan de generatie nog lopen, dus de client-timeout staat ruim.
"""
import json
import time

import httpx

from . import config


class QwenFout(RuntimeError):
    pass


class Qwen:
    def __init__(self, base_url: str | None = None, model: str | None = None,
                 timeout_s: float = 1000.0, pogingen: int = 3, backoff_s: tuple = (15, 60, 180)):
        base = (base_url if base_url is not None else config.QWEN_BASE_URL).rstrip("/")
        if not base:
            raise QwenFout("QWEN_BASE_URL ontbreekt (bijvoorbeeld http://localhost:8080/v1)")
        if config.VERBODEN_LLM_HOST and config.VERBODEN_LLM_HOST in base:
            raise QwenFout(f"Rechtstreeks naar {config.VERBODEN_LLM_HOST} is niet toegestaan (QWEN_VERBODEN_HOST)")
        self.base = base
        self.model = model or config.QWEN_MODEL
        self.pogingen = pogingen
        self.backoff_s = backoff_s
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10.0))

    def chat_json(self, berichten: list[dict], schema: dict, naam: str = "uitvoer",
                  max_tokens: int = 600, temperatuur: float = 0.1) -> tuple[dict, dict]:
        """Chat-completion met afgedwongen JSON-schema. Geeft (object, meta).

        Bij 5xx/timeout: retry met backoff (max `pogingen`). Bij onleesbare JSON:
        één extra poging, daarna QwenFout.
        """
        body = {
            "model": self.model,
            "messages": berichten,
            "temperature": temperatuur,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": naam, "strict": True, "schema": schema},
            },
        }
        parse_pogingen = 0
        laatste_fout = None
        poging = 0
        while poging < self.pogingen:
            start = time.monotonic()
            try:
                r = self.client.post(f"{self.base}/chat/completions", json=body)
            except httpx.HTTPError as e:
                laatste_fout = f"{type(e).__name__}: {e}"
                self._slaap(poging)
                poging += 1
                continue
            latency = time.monotonic() - start
            if r.status_code >= 500 or r.status_code == 429:
                laatste_fout = f"HTTP {r.status_code}: {r.text[:200]}"
                self._slaap(poging)
                poging += 1
                continue
            if r.status_code != 200:
                raise QwenFout(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            keuze = data["choices"][0]
            inhoud = keuze["message"].get("content") or ""
            try:
                obj = json.loads(inhoud)
                if not isinstance(obj, dict):
                    raise ValueError("geen object")
            except ValueError as e:
                parse_pogingen += 1
                laatste_fout = f"onleesbare JSON ({e}); finish_reason={keuze.get('finish_reason')}"
                if parse_pogingen > 1:
                    raise QwenFout(laatste_fout)
                continue
            meta = {
                "latency_s": round(latency, 2),
                "model": data.get("model"),
                "usage": data.get("usage", {}),
                "timings": data.get("timings", {}),
                "finish_reason": keuze.get("finish_reason"),
            }
            return obj, meta
        raise QwenFout(f"na {self.pogingen} pogingen: {laatste_fout}")

    def _slaap(self, poging: int) -> None:
        if poging + 1 < self.pogingen:
            time.sleep(self.backoff_s[min(poging, len(self.backoff_s) - 1)])
