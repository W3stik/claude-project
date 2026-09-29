from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from daytrader.ai import FALLBACK_BETA, AIAnalyst, AIError, build_prompt  # noqa: E402
from daytrader.models import NewsItem  # noqa: E402


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(response):
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def response(stop_reason="end_turn", text="**Shrnutí** – test"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1200, output_tokens=800),
    )


def test_analyze_returns_text_and_uses_fallbacks():
    client, messages = fake_client(response())
    analyst = AIAnalyst(client=client, model="claude-opus-5-5", effort="medium")
    result = analyst.analyze({"symbol": "AAPL", "price": 100.0}, [NewsItem(title="Apple news")], "Kde je support?")
    assert result.text == "**Shrnutí** – test"
    assert result.estimated_cost_usd == pytest.approx((1200 * 4 + 800 * 20) / 1e6)
    assert messages.kwargs["model"] == "claude-opus-5-5"
    assert messages.kwargs["fallbacks"] == "default"
    assert messages.kwargs["betas"] == [FALLBACK_BETA]
    assert messages.kwargs["output_config"] == {"effort": "medium"}
    prompt = messages.kwargs["messages"][0]["content"]
    assert "AAPL" in prompt and "Apple news" in prompt and "Kde je support?" in prompt


def test_refusal_raises():
    client, _ = fake_client(response(stop_reason="refusal", text=""))
    with pytest.raises(AIError):
        AIAnalyst(client=client).analyze({"symbol": "AAPL"})


def test_max_tokens_is_flagged():
    client, _ = fake_client(response(stop_reason="max_tokens"))
    assert "zkrácena" in AIAnalyst(client=client).analyze({"symbol": "AAPL"}).text


def test_prompt_is_deterministic_json():
    a = build_prompt({"b": 1, "a": 2})
    b = build_prompt({"a": 2, "b": 1})
    assert a == b
