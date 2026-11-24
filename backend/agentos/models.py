"""Typed agent contracts and official-SDK provider adapter (no simulated live mode)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

T = TypeVar("T", bound=BaseModel)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Step(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    agent: Literal["research", "data", "action"]
    instruction: str = Field(min_length=1, max_length=2000)
    dependencies: list[str] = Field(default_factory=list)
    tool: str | None = None
    arguments: dict = Field(default_factory=dict)
    completion_criteria: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    checks: list[CompletionCheck] = Field(default_factory=list, max_length=8)


class Plan(StrictModel):
    steps: list[Step] = Field(default_factory=list, max_length=12)
    refusal: str | None = None
    clarification: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_dag(self):
        if self.steps and (self.refusal or self.clarification):
            raise ValueError("Refusal/clarification cannot contain executable steps")
        if self.refusal and self.clarification:
            raise ValueError("Choose refusal or clarification")
        if not self.steps and not self.refusal and not self.clarification:
            raise ValueError("Plan needs steps or an explicit refusal")
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate step IDs")
        edges = {s.id: set(s.dependencies) for s in self.steps}
        if any(not deps <= set(ids) for deps in edges.values()):
            raise ValueError("Unknown dependency")
        completed = set()
        while len(completed) < len(ids):
            ready = {i for i, d in edges.items() if i not in completed and d <= completed}
            if not ready:
                raise ValueError("Cyclic dependency graph")
            completed |= ready
        return self


class SelectedCapability(StrictModel):
    capability: Literal[
        "document_search",
        "business_metrics",
        "invoice_analysis",
        "inventory_retrieval",
        "create_report",
        "export_csv",
        "create_followup",
        "draft_email",
        "update_inventory",
        "create_notification",
    ]
    instruction: str = Field(min_length=1, max_length=2000)


class CapabilityTask(SelectedCapability):
    after: list[int] = Field(default_factory=list, max_length=11)


class OrderedTask(SelectedCapability):
    uses_prior_results: bool


class OrderedPlan(StrictModel):
    """A model may request a dependency barrier without copying positional indexes."""

    tasks: list[OrderedTask] = Field(max_length=12)
    clarification: str | None = None
    refusal: str | None = None

    def indexed(self) -> CapabilityPlan:
        return CapabilityPlan(
            tasks=[
                CapabilityTask(
                    capability=task.capability,
                    instruction=task.instruction,
                    after=list(range(i)) if task.uses_prior_results else [],
                )
                for i, task in enumerate(self.tasks)
            ],
            clarification=self.clarification,
            refusal=self.refusal,
        )


class ReadOnlyTask(OrderedTask):
    capability: Literal[
        "document_search", "business_metrics", "invoice_analysis", "inventory_retrieval"
    ]


class ReadOnlyPlan(OrderedPlan):
    tasks: list[ReadOnlyTask] = Field(max_length=12)


class CapabilityPlan(StrictModel):
    """Compact tool-first wire format for constrained structured-decoding servers."""

    tasks: list[CapabilityTask] = Field(max_length=12)
    clarification: str | None = None
    refusal: str | None = None


class Claim(StrictModel):
    text: str = Field(max_length=1500)
    citations: list[str] = Field(default_factory=list)
    kind: Literal[
        "unclassified", "extractive", "source", "numeric", "trend", "causal", "action"
    ] = "unclassified"
    quote: str | None = Field(default=None, max_length=2200)
    metric: Literal["revenue", "costs", "profit", "margin"] | None = None
    operation: Literal["total", "point", "growth", "change"] = "total"
    value: float | None = None
    start: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    end: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    basis: Literal["interval", "mom", "yoy", "previous_period"] = "interval"
    direction: Literal["increase", "decrease", "flat"] | None = None
    receipt: str | None = None


class Finding(StrictModel):
    summary: str = Field(max_length=6000)
    citations: list[str] = Field(default_factory=list)
    insufficient: bool = False
    contradictions: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)


class EvidenceQuote(StrictModel):
    source: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=1200)


class CitedSynthesis(StrictModel):
    """Compact research response. Host restores durable source IDs after decoding."""

    summary: str = Field(min_length=1, max_length=3000)
    evidence: list[EvidenceQuote] = Field(max_length=8)
    contradictions: list[str] = Field(max_length=4)
    insufficient: bool

    def finding(self) -> Finding:
        return Finding(
            summary=self.summary,
            citations=list(dict.fromkeys(item.source for item in self.evidence)),
            contradictions=self.contradictions,
            insufficient=self.insufficient,
            claims=[
                Claim(text=item.quote, quote=item.quote, citations=[item.source], kind="extractive")
                for item in self.evidence
            ],
        )


def cited_synthesis_schema(references):
    """Constrain citation decoding to this retrieval result's actual passage IDs."""
    ids = tuple(references)
    if not ids:
        return create_model(
            "EmptySynthesis",
            __base__=CitedSynthesis,
            evidence=(list[EvidenceQuote], Field(max_length=0)),
        )
    quote = create_model("PassageQuote", __base__=EvidenceQuote, source=(Literal[ids], ...))
    return create_model(
        "PassageSynthesis", __base__=CitedSynthesis, evidence=(list[quote], Field(max_length=8))
    )


class RecordInterpretation(StrictModel):
    summary: str = Field(min_length=1, max_length=2400)
    insufficient: bool

    def finding(self) -> Finding:
        return Finding(**self.model_dump())


class TrendReading(StrictModel):
    metric: Literal["revenue", "costs", "profit", "margin"]
    start: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    end: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    basis: Literal["interval", "mom", "yoy"]
    direction: Literal["increase", "decrease", "flat"]


class ComputedInterpretation(StrictModel):
    summary: str = Field(min_length=1, max_length=2400)
    trends: list[TrendReading] = Field(max_length=4)
    insufficient: bool

    def finding(self) -> Finding:
        return Finding(
            summary=self.summary,
            insufficient=self.insufficient,
            claims=[
                Claim(
                    text=f"{trend.metric}: {trend.direction} from {trend.start} to {trend.end}",
                    kind="trend",
                    operation="change",
                    **trend.model_dump(),
                )
                for trend in self.trends
            ],
        )


class SearchQuery(StrictModel):
    query: str = Field(min_length=1, max_length=1000)
    alternatives: list[str] = Field(default_factory=list, max_length=3)


class Review(StrictModel):
    supported: bool
    issues: list[str] = Field(default_factory=list)


class AnalyticsIntent(StrictModel):
    as_of: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    dataset: Literal["sales", "inventory", "invoices"] = "sales"
    metrics: list[Literal["revenue", "costs", "profit", "margin"]] = Field(
        default_factory=lambda: ["revenue"], min_length=1, max_length=4
    )
    start: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    end: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    compare_previous: bool = False

    @model_validator(mode="after")
    def valid_period(self):
        for period in [self.start, self.end]:
            if period and not 1 <= int(period[-2:]) <= 12:
                raise ValueError("Invalid calendar month")
        if self.start and self.end and self.start > self.end:
            raise ValueError("Reversed period")
        return self


class ActionSpec(StrictModel):
    tool: Literal[
        "create_report",
        "export_csv",
        "create_followup",
        "draft_email",
        "update_inventory",
        "create_notification",
    ]
    arguments: dict


class ProviderError(RuntimeError):
    pass


class BudgetExceeded(ProviderError):
    pass


class Provider:
    """SDK tool calling with strict client-side validation, bounded retries and accounting.

    Optional http_client is for transport-level tests, never a fake provider mode.
    Ledger hooks reserve conservative token ceilings before each attempt.
    """

    def __init__(self, mode="demo", model=None, *, http_client=None, ledger=None, trace=None):
        self.mode = mode
        self.model = model or os.getenv(
            "OPENAI_MODEL" if mode == "openai" else "ANTHROPIC_MODEL",
            "gpt-4.1-mini" if mode == "openai" else "claude-sonnet-4-5",
        )
        self.http_client = http_client
        self.ledger = ledger
        self.trace = trace
        self.tokens = 0
        self.calls = 0
        self.records = []

    async def structured(self, schema: type[T], system: str, payload: str) -> T:
        if self.mode not in {"openai", "anthropic"}:
            raise ProviderError("Offline demo does not call a model")
        payload = payload[:24000]
        system = system[:6000]
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "30"))
        if not 1 <= timeout <= 180:
            raise ValueError("MODEL_TIMEOUT_SECONDS must be between 1 and 180")
        output_limit = int(os.getenv("MODEL_MAX_OUTPUT_TOKENS", "1800"))
        schema_text = json.dumps(schema.model_json_schema())
        schema_copies = (
            2
            if self.mode == "openai" and os.getenv("OPENAI_STRUCTURED_OUTPUT") == "json_schema"
            else 1
        )
        estimate = (
            len((system + payload + schema_text * schema_copies).encode()) + output_limit + 256
        )
        fallbacks = json.loads(os.getenv("MODEL_FALLBACKS", "{}")).get(self.model, [])
        models = [self.model] + fallbacks[:1]
        last = None
        for model in models:
            model_prices = json.loads(os.getenv("MODEL_PRICES", "{}")).get(model)
            for attempt in range(3):
                reservation = self.ledger.reserve(estimate, model_prices) if self.ledger else None
                start = time.perf_counter()
                record = {
                    "provider": self.mode,
                    "model": model,
                    "prompt_version": "agentos-v3.1",
                    "usage_known": False,
                    "response_received": False,
                    "schema": schema.__name__,
                    "attempt": attempt + 1,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost_usd": None,
                }
                client = None
                try:
                    if self.mode == "openai":
                        from openai import AsyncOpenAI

                        client = AsyncOpenAI(
                            api_key=os.getenv("OPENAI_API_KEY"),
                            base_url=os.getenv("OPENAI_BASE_URL") or None,
                            http_client=self.http_client,
                            max_retries=0,
                            timeout=timeout,
                        )
                        protocol = os.getenv("OPENAI_STRUCTURED_OUTPUT", "tool")
                        parameters = schema.model_json_schema()
                        if protocol == "json_schema":
                            # Some compatible servers constrain decoding without describing the schema in the prompt.
                            wire_system = (
                                system
                                + "\nReturn a concise JSON object using this schema. Omit optional fields when inapplicable.\n"
                                + json.dumps(parameters, separators=(",", ":"))
                            )
                            options = {
                                "response_format": {
                                    "type": "json_schema",
                                    "json_schema": {"name": schema.__name__, "schema": parameters},
                                }
                            }
                        elif protocol == "tool":
                            wire_system = system
                            choice = (
                                "required"
                                if os.getenv("OPENAI_TOOL_CHOICE") == "required"
                                else {"type": "function", "function": {"name": "emit_result"}}
                            )
                            options = {
                                "tools": [
                                    {
                                        "type": "function",
                                        "function": {
                                            "name": "emit_result",
                                            "description": "Return the validated structured result",
                                            "parameters": parameters,
                                        },
                                    }
                                ],
                                "tool_choice": choice,
                            }
                        else:
                            raise ValueError("Unsupported OpenAI structured output protocol")
                        record["protocol"] = protocol
                        response = await asyncio.wait_for(
                            client.chat.completions.create(
                                model=model,
                                messages=[
                                    {"role": "system", "content": wire_system},
                                    {"role": "user", "content": payload},
                                ],
                                max_tokens=output_limit,
                                **options,
                            ),
                            timeout + 10,
                        )
                        record["response_received"] = True
                        if response.usage:
                            record.update(
                                input_tokens=response.usage.prompt_tokens,
                                output_tokens=response.usage.completion_tokens,
                                usage_known=True,
                            )
                        if not response.choices:
                            raise ProviderError("No completion choices")
                        message = response.choices[0].message
                        if protocol == "json_schema":
                            if not message.content or message.tool_calls:
                                raise ProviderError("Missing structured JSON content")
                            value = message.content
                        else:
                            if len(message.tool_calls or []) != 1:
                                raise ProviderError("Expected exactly one structured tool response")
                            call = message.tool_calls[0]
                            if call.function.name != "emit_result":
                                raise ProviderError("Unexpected tool response")
                            value = call.function.arguments
                    else:
                        from anthropic import AsyncAnthropic

                        client = AsyncAnthropic(
                            api_key=os.getenv("ANTHROPIC_API_KEY"),
                            base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
                            http_client=self.http_client,
                            max_retries=0,
                            timeout=timeout,
                        )
                        response = await asyncio.wait_for(
                            client.messages.create(
                                model=model,
                                system=system,
                                messages=[{"role": "user", "content": payload}],
                                tools=[
                                    {
                                        "name": "emit_result",
                                        "description": "Return structured output",
                                        "input_schema": schema.model_json_schema(),
                                    }
                                ],
                                tool_choice="required"
                                if os.getenv("OPENAI_TOOL_CHOICE") == "required"
                                else {"type": "tool", "name": "emit_result"},
                                max_tokens=output_limit,
                            ),
                            timeout + 10,
                        )
                        record["response_received"] = True
                        record.update(
                            input_tokens=response.usage.input_tokens,
                            output_tokens=response.usage.output_tokens,
                            usage_known=True,
                        )
                        blocks = [
                            b
                            for b in response.content
                            if b.type == "tool_use" and b.name == "emit_result"
                        ]
                        if len(blocks) != 1:
                            raise ProviderError("Missing structured tool response")
                        value = blocks[0].input
                        record.update(
                            input_tokens=response.usage.input_tokens,
                            output_tokens=response.usage.output_tokens,
                        )
                    return schema.model_validate(
                        json.loads(value) if isinstance(value, str) else value
                    )
                except Exception as exc:
                    last = exc
                    record["error"] = type(exc).__name__
                    code = getattr(exc, "status_code", None)
                    transient = (
                        isinstance(exc, (TimeoutError, httpx.TransportError))
                        or code in {408, 409, 429, 500, 502, 503, 504}
                        or type(exc).__name__ in {"APITimeoutError", "APIConnectionError"}
                    )
                    if not transient:
                        raise ProviderError(
                            f"{self.mode} structured response failed: {type(exc).__name__}"
                        ) from exc
                    if attempt < 2:
                        await asyncio.sleep(0.1 * 2**attempt)
                finally:
                    record["seconds"] = time.perf_counter() - start
                    self.records.append(record)
                    record["tokens"] = (
                        record["input_tokens"] + record["output_tokens"]
                        if record["usage_known"]
                        else None
                    )
                    if record["response_received"]:
                        self.calls += 1
                    if record["usage_known"]:
                        self.tokens += record["tokens"]
                        if model_prices:
                            record["estimated_cost_usd"] = (
                                record["input_tokens"] * model_prices["input"]
                                + record["output_tokens"] * model_prices["output"]
                            ) / 1e6
                    if self.trace:
                        self.trace(record)
                    # Unknown billed usage retains reservation conservatively.
                    if reservation and self.ledger:
                        if record["usage_known"]:
                            self.ledger.settle(
                                reservation,
                                record["input_tokens"] + record["output_tokens"],
                                record["estimated_cost_usd"],
                            )
                        else:
                            self.ledger.uncertain(reservation)
                    if client and self.http_client is None:
                        await client.close()
        raise ProviderError(
            f"{self.mode} request failed after bounded retries: {type(last).__name__}"
        ) from last


class CompletionCheck(StrictModel):
    """Machine-checkable predicates, separate from narrative completion criteria."""

    kind: Literal["metric", "source_count", "tool", "action_receipt"]
    metric: Literal["revenue", "costs", "profit", "margin"] | None = None
    expected: float | None = None
    minimum: int = Field(default=1, ge=1, le=20)
    tool: str | None = None


Step.model_rebuild()
Plan.model_rebuild()
