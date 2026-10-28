import json

import httpx
import pytest

from app.config import Settings
from app.providers import OllamaProvider, ProviderError
from app.schemas import Analysis


async def test_empty_model_inventory_is_explicit(tmp_path):
    provider = OllamaProvider(Settings(data_dir=tmp_path), httpx.MockTransport(lambda request: httpx.Response(200, json={"models": []})))
    state = await provider.health()
    assert not state["available"] and state["models"] == []
    with pytest.raises(ProviderError, match="Gemma"):
        await provider.generate("instruction", {}, Analysis)


async def test_structured_output_and_raw_context_redaction(tmp_path):
    requests = []
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma3:4b"}]})
        requests.append(json.loads(request.content))
        response = {"summary": "Fixture hypothesis", "hypotheses": [{"id": "h1", "title": "Fixture", "reasoning": "Fixture", "confidence": 0.5, "supporting_evidence": ["e1"], "contradicting_evidence": [], "diagnostic_checks": []}]}
        return httpx.Response(200, json={"message": {"content": json.dumps(response)}})
    provider = OllamaProvider(Settings(data_dir=tmp_path), httpx.MockTransport(handler))
    context = {
        "evidence": [{"content": "password=do-not-send"}, {"raw_json": '{"password": "nested-json-secret", "api_key": "nested-api-secret"}'}],
        "nested": [{"deeper": ['client_secret="nested-list-secret"']}],
        "password=secret-in-key": "safe content",
    }
    analysis = await provider.generate("instruction", context, Analysis)
    assert analysis.hypotheses[0].id == "h1"
    assert requests[0]["format"]["type"] == "object" and not requests[0]["stream"]
    for secret in ("do-not-send", "nested-json-secret", "nested-api-secret", "nested-list-secret", "secret-in-key"):
        assert secret not in requests[0]["messages"][1]["content"]


@pytest.mark.parametrize("inventory", [None, [], {"models": None}, {"models": "gemma3:4b"}, {"models": {}}, {"models": ["gemma3:4b"]}, {"models": [{"name": None}]}, {"models": [{"name": ""}]}])
async def test_malformed_model_inventory_is_unavailable(tmp_path, inventory):
    provider = OllamaProvider(Settings(data_dir=tmp_path), httpx.MockTransport(lambda request: httpx.Response(200, json=inventory)))
    result = await provider.health()
    assert result["available"] is False
    assert "invalid model inventory" in result["error"]


async def test_malformed_model_response_retries_then_fails(tmp_path):
    count = 0
    def handler(request):
        nonlocal count
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma3:4b"}]})
        count += 1
        return httpx.Response(200, json={"message": {"content": "not json"}})
    provider = OllamaProvider(Settings(data_dir=tmp_path), httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="malformed"):
        await provider.generate("instruction", {}, Analysis)
    assert count == 2


@pytest.mark.parametrize("url", ["https://example.com", "http://user:secret@localhost:11434", "http://192.168.0.1:11434"])
def test_remote_provider_egress_is_disabled(tmp_path, url):
    with pytest.raises(ValueError, match="loopback"):
        Settings(data_dir=tmp_path, ollama_url=url)


async def test_cloud_tag_is_not_selected(tmp_path):
    provider = OllamaProvider(Settings(data_dir=tmp_path), httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "gemma:cloud"}]})))
    assert not (await provider.health())["available"]
