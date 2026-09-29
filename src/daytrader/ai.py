"""Optional AI commentary on the technical snapshot using the Claude API (paid per use).

Only the computed indicator snapshot and news headlines are sent - never account data
or API keys of other services.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .models import NewsItem

SYSTEM_PROMPT = """You are an experienced, sober intraday trading analyst and risk coach.
You receive a JSON snapshot of technical indicators and price levels that a trading app
computed for one instrument, optionally with recent news headlines and a question from
the trader.

Write in Czech, as concise Markdown (max ~250 words) with these sections:
**Shrnutí** – what the data says right now in 2–3 sentences.
**Klíčové úrovně** – the few levels from the data that matter most and why.
**Scénáře** – a bullish and a bearish scenario: what would confirm each, where it is invalidated.
**Rizika** – volatility, liquidity, news or data caveats worth respecting.

Use only numbers present in the input; if something important is missing, say so.
Describe probabilities and conditions, not certainties. This is educational analysis,
not personal investment advice – do not tell the trader to buy or sell; frame ideas as
conditions to watch and always tie them to a stop-loss / risk limit."""

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens (input, output) – for a rough cost estimate shown in the UI.
PRICING = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


class AIError(RuntimeError):
    pass


@dataclass
class AIResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def estimated_cost_usd(self) -> float | None:
        prices = PRICING.get(self.model)
        if prices is None:
            return None
        return (self.input_tokens * prices[0] + self.output_tokens * prices[1]) / 1_000_000


def build_prompt(snapshot: dict[str, Any], news: list[NewsItem] | None = None, question: str | None = None) -> str:
    payload: dict[str, Any] = {"snapshot": snapshot}
    if news:
        payload["news"] = [
            {
                "title": item.title,
                "source": item.source,
                "published": item.published.isoformat() if item.published else None,
            }
            for item in news[:8]
        ]
    text = "Data z aplikace:\n```json\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n```"
    if question:
        text += f"\n\nOtázka obchodníka: {question.strip()}"
    return text


class AIAnalyst:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        client: Any | None = None,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise AIError("AI analýza potřebuje balíček anthropic: pip install 'daytrader[ai]'") from exc
        self._anthropic = anthropic
        self.client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
        self.model = model
        self.effort = effort

    def analyze(
        self,
        snapshot: dict[str, Any],
        news: list[NewsItem] | None = None,
        question: str | None = None,
    ) -> AIResult:
        anthropic = self._anthropic
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(snapshot, news, question)}],
                output_config={"effort": self.effort},
                # If a safety classifier declines, retry server-side on Anthropic's recommended model.
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise AIError("Neplatný ANTHROPIC_API_KEY – zkontroluj ho v souboru .env.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AIError("API klíč nemá oprávnění k tomuto modelu.") from exc
        except anthropic.NotFoundError as exc:
            raise AIError(f"Model {self.model} neexistuje – uprav DT_AI_MODEL.") from exc
        except anthropic.RateLimitError as exc:
            raise AIError("Překročen limit požadavků Claude API – zkus to za chvíli.") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"Chyba Claude API ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("Nelze se připojit ke Claude API – zkontroluj internet.") from exc

        if response.stop_reason == "refusal":
            raise AIError("Model tento požadavek odmítl zpracovat.")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n_(Odpověď byla zkrácena limitem délky.)_"
        usage = getattr(response, "usage", None)
        return AIResult(
            text=text or "_(Model nevrátil žádný text.)_",
            model=getattr(response, "model", self.model) or self.model,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )
