"""Cluster-label LLM providers behind one interface.

Chosen provider: Gemini (per project decision). OpenAI/Anthropic are stubbed as
drop-ins. If the selected provider has no key and `fallback_to_heuristic` is set,
the caller (pipeline/label.py) uses a keyword-based heuristic instead — so the
pipeline never hard-blocks on a missing key.

Contract: `name_cluster(prompt) -> str` returns a short evocative label.
"""

from __future__ import annotations

from typing import Protocol

from ..config import LabelingCfg, Secrets

SYSTEM_INSTRUCTION = (
    "You name clusters of films from someone's personal collection. Given a list of "
    "titles (and sometimes recurring keywords), reply with ONE short, evocative label "
    "of 2-5 words capturing the shared mood/theme/phase — like 'slow-cinema grief' or "
    "'neon-soaked heists'. No quotes, no punctuation at the end, no explanation."
)

THEME_INSTRUCTION = (
    "You extract abstract THEMES from a film or TV show — the underlying motifs, not the "
    "plot, genre, or setting. Given the title, overview and keywords, reply with 4-6 "
    "short abstract theme phrases, comma-separated, lowercase, no explanation. Prefer "
    "universal motifs like 'mortality', 'moral corruption', 'coming of age', "
    "'isolation', 'redemption', 'obsession', 'class conflict', 'loss of innocence', "
    "'man vs nature', 'fate vs free will'. Avoid plot specifics and genre words."
)


def _parse_themes(raw: str) -> list[str]:
    parts = [p.strip().strip(".").strip('"').strip("'").lower()
             for chunk in (raw or "").replace("\n", ",").split(",") for p in [chunk]]
    out: list[str] = []
    for p in parts:
        if p and 2 <= len(p) <= 40 and p not in out:
            out.append(p)
    return out[:6]


class LabelProvider(Protocol):
    name: str

    def name_cluster(self, prompt: str) -> str:
        ...


class GeminiLabelProvider:
    def __init__(self, model: str, api_key: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY missing")
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "google-genai not installed. `pip install google-genai` "
                "or set [labeling].provider to 'heuristic'."
            ) from exc
        self.name = model
        self._client = genai.Client(api_key=api_key)

    def _generate(self, prompt: str, system_instruction: str, max_tokens: int) -> str:
        import re
        import time

        from google.genai import types

        cfg = types.GenerateContentConfig(
            system_instruction=system_instruction, max_output_tokens=max_tokens,
            temperature=0.9,
        )
        try:  # Gemini 2.5 "thinking" would eat the small token budget — disable it.
            if "2.5" in self.name or "pro" in self.name or self.name.endswith("latest"):
                cfg.thinking_config = types.ThinkingConfig(thinking_budget=0)
        except Exception:  # noqa: BLE001
            pass

        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                resp = self._client.models.generate_content(
                    model=self.name, contents=prompt, config=cfg)
                return resp.text or ""
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc)
                # Retry transient per-minute limits (honour retryDelay); a per-DAY
                # quota won't recover by waiting, so fail fast for the caller to stop.
                is_daily = "PerDay" in msg
                if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and not is_daily and attempt < 4:
                    m = re.search(r"retryDelay'?:?\s*'?(\d+(?:\.\d+)?)s", msg)
                    delay = float(m.group(1)) + 1.0 if m else (2 + attempt * 3)
                    time.sleep(min(delay, 20.0))
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    def name_cluster(self, prompt: str) -> str:
        return _clean(self._generate(prompt, SYSTEM_INSTRUCTION, 40))

    def extract_themes(self, prompt: str) -> list[str]:
        raw = self._generate(prompt, THEME_INSTRUCTION, 60)
        return _parse_themes(raw)


class OpenAILabelProvider:  # drop-in stub
    def __init__(self, model: str, api_key: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY missing")
        from openai import OpenAI

        self.name = model
        self._client = OpenAI(api_key=api_key)

    def name_cluster(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.name,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            max_tokens=20,
        )
        return _clean(resp.choices[0].message.content or "")


class AnthropicLabelProvider:  # drop-in stub
    def __init__(self, model: str, api_key: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY missing")
        import anthropic

        self.name = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def name_cluster(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.name,
            max_tokens=20,
            system=SYSTEM_INSTRUCTION,
            messages=[{"role": "user", "content": prompt}],
        )
        return _clean("".join(b.text for b in msg.content if b.type == "text"))


def _clean(text: str) -> str:
    return text.strip().strip('"').strip("'").rstrip(".").strip()[:60]


def build_label_provider(cfg: LabelingCfg, secrets: Secrets) -> LabelProvider | None:
    """Return a provider, or None if it can't be built (caller falls back)."""
    try:
        if cfg.provider == "gemini":
            return GeminiLabelProvider(cfg.gemini_model, secrets.gemini_api_key)
        if cfg.provider == "openai":
            return OpenAILabelProvider("gpt-4o-mini", secrets.openai_api_key)
        if cfg.provider == "anthropic":
            return AnthropicLabelProvider("claude-haiku-4-5-20251001", secrets.anthropic_api_key)
    except (ValueError, ImportError) as exc:
        print(f"[label] LLM provider '{cfg.provider}' unavailable: {exc}")
        return None
    return None  # provider == "heuristic"
