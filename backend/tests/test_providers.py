import json

import httpx
import pytest

from agentos.models import Provider, ProviderError, SearchQuery


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["openai", "anthropic"])
async def test_official_sdk_transport(mode, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-transport-only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-transport-only")
    if mode == "anthropic":
        import httpx2 as transport_http
    else:
        transport_http = httpx
    captured = []

    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        assert "tools" in body
        if mode == "openai":
            return httpx.Response(
                200,
                json={
                    "id": "mock-response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "emit_result",
                                            "arguments": json.dumps(
                                                {
                                                    "query": "subscription churn",
                                                    "alternatives": ["customer retention"],
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 12, "total_tokens": 62},
                },
            )
        return transport_http.Response(
            200,
            json={
                "id": "mock-response",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "emit_result",
                        "input": {
                            "query": "subscription churn",
                            "alternatives": ["customer retention"],
                        },
                    }
                ],
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 50, "output_tokens": 12},
            },
        )

    async with transport_http.AsyncClient(
        transport=transport_http.MockTransport(respond)
    ) as client:
        provider = Provider(mode, "test-model", http_client=client)
        answer = await provider.structured(SearchQuery, "Rewrite safely", "Why do customers leave?")
    assert answer.query == "subscription churn"
    assert provider.tokens == 62
    assert provider.records[0]["provider"] == mode
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_rate_limit_retry_and_cost(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("MODEL_PRICES", json.dumps({"priced-model": {"input": 1.0, "output": 2.0}}))
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                429,
                json={"error": {"message": "limited", "type": "rate_limit_error"}},
                headers={"retry-after": "0"},
            )
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "priced-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "type": "function",
                                    "function": {
                                        "name": "emit_result",
                                        "arguments": '{"query":"revenue"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = Provider("openai", "priced-model", http_client=client)
        await p.structured(SearchQuery, "Rewrite", "Revenue?")
    assert len(calls) == 2
    assert p.records[0]["error"] == "RateLimitError"
    assert p.records[-1]["estimated_cost_usd"] == 0.00002


@pytest.mark.asyncio
async def test_invalid_structured_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "x",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "not a tool"}}
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError):
            await Provider("openai", "x", http_client=client).structured(
                SearchQuery, "system", "user"
            )


@pytest.mark.asyncio
async def test_timeout_and_configured_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("MODEL_FALLBACKS", '{"primary":["fallback"]}')
    calls = []

    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "primary":
            raise httpx.ReadTimeout("injected timeout")
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "type": "function",
                                    "function": {
                                        "name": "emit_result",
                                        "arguments": '{"query":"fallback works"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Provider("openai", "primary", http_client=client).structured(
            SearchQuery, "system", "user"
        )
    assert result.query == "fallback works"
    assert calls == ["primary", "primary", "primary", "fallback"]
