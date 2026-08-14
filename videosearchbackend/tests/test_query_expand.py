"""Unit tests for the optional LLM query-expansion "middleman".

The LLM call is mocked — these must never hit the network.
"""

import json
import urllib.request

from app.core.config import get_settings
from app.videos import query_expand


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:  # pragma: no cover - trivial
        return False

    def read(self) -> bytes:
        return self._body


def _enable_llm(monkeypatch, prompts: int = 2) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_expand_prompts", prompts)


def _json_choice(content: str) -> bytes:
    body = {"choices": [{"message": {"content": content}}]}
    return json.dumps(body).encode()


def test_without_key_uses_raw_prompt(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    assert query_expand.expand_prompt("car red road") == ["car red road"]


def test_expand_returns_raw_plus_parsed_variants(monkeypatch) -> None:
    _enable_llm(monkeypatch, prompts=2)
    variants = ["a red car on a highway at sunset", "red sports car driving down a road"]
    content = json.dumps({"variants": variants})
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_json_choice(content)),
    )

    result = query_expand.expand_prompt("red car road")
    assert result[0] == "red car road"  # raw prompt always first
    assert result[1:] == variants


def test_expand_drops_empty_or_short_variants(monkeypatch) -> None:
    _enable_llm(monkeypatch, prompts=3)
    content = json.dumps({"variants": ["a red car on a highway", "", "x", "a green field"]})
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_json_choice(content)),
    )
    result = query_expand.expand_prompt("car")
    assert result[1:] == ["a red car on a highway", "a green field"]


def test_expand_recovers_from_prose_wrapped_json(monkeypatch) -> None:
    _enable_llm(monkeypatch, prompts=1)
    prose = 'Sure! Here are some options: {"variants": ["a red car at dusk"]} Hope that helps.'
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_json_choice(prose)),
    )
    result = query_expand.expand_prompt("car dusk")
    assert "a red car at dusk" in result[1:]


def test_expand_failure_falls_back_to_raw_prompt(monkeypatch) -> None:
    _enable_llm(monkeypatch)

    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert query_expand.expand_prompt("anything at all") == ["anything at all"]


def test_expand_failure_on_bad_json_falls_back_to_raw(monkeypatch) -> None:
    _enable_llm(monkeypatch)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(_json_choice("no json here at all")),
    )
    assert query_expand.expand_prompt("anything") == ["anything"]
