"""Capability probe for the configured endpoint.

The ChatAnywhere documentation states the service is OpenAI-compatible but says
nothing about structured-output support, and relays differ in what they forward.
Rather than guess, ``printpilot llm-check`` asks the endpoint directly and reports
what actually worked.

The probe is cheap on purpose: a handful of short calls, so it can be re-run after
switching model or provider without thinking about cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from printpilot.domain import DiagnosisResult
from printpilot.llm.base import LLMError
from printpilot.llm.config import LLMSettings, StructuredMode
from printpilot.llm.openai_compatible import OpenAICompatibleClient


class ProbeAnswer(BaseModel):
    """Small schema with a mix of types — enough to catch a provider that returns
    JSON-shaped prose or coerces everything to strings."""

    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(description="Exactly the word 'ok'.")
    count: int = Field(description="The integer 3.")
    ratio: float = Field(description="The number 0.5.")
    tags: list[str] = Field(description="Exactly ['a', 'b'].")


PROBE_PROMPT = (
    "Respond with verdict='ok', count=3, ratio=0.5, tags=['a','b']. Use the exact types requested."
)


#: The schema the pipeline actually sends. Probing only with a flat toy schema is
#: misleading: strict `json_schema` mode constrains nested models, `$defs`
#: references, enums and defaulted fields, none of which a four-field probe
#: exercises. A mode is only usable here if it works on *this*.
REAL_PROMPT = (
    "遥测显示：流量比尾段 0.81（低于正常 0.985），挤出机电流变化量 +0.09 A（正常带 ±0.01）。"
    "材料 PLA。给出根因假设，fault_code 必须取自枚举，并引用证据。case_id 用 'probe-1'。"
)


@dataclass
class ModeResult:
    mode: StructuredMode
    schema_name: str
    ok: bool
    detail: str = ""
    latency_ms: float = 0.0


@dataclass
class ProbeReport:
    reachable: bool
    models: list[str] = field(default_factory=list)
    model_listed: bool | None = None
    modes: list[ModeResult] = field(default_factory=list)
    error: str = ""

    @property
    def best_mode(self) -> StructuredMode | None:
        """Strictest mode that worked **on the real schema**.

        Strict schema is preferred when genuinely available: it moves validation
        upstream and cuts the repair-retry rate. But a mode that only handles the
        toy schema is not available for our purposes, so the toy result cannot
        promote a mode on its own.
        """
        order = [
            StructuredMode.JSON_SCHEMA,
            StructuredMode.JSON_OBJECT,
            StructuredMode.PROMPT_ONLY,
        ]
        working = {r.mode for r in self.modes if r.ok and r.schema_name == "DiagnosisResult"}
        return next((m for m in order if m in working), None)


def list_models(settings: LLMSettings) -> list[str]:
    """``GET /v1/models``. Not every relay implements it; an empty list is a
    valid answer, not a failure."""
    client = OpenAICompatibleClient(settings=settings)
    try:
        page = client._api().models.list()
    except Exception:
        return []
    return sorted(item.id for item in page.data)


def probe(settings: LLMSettings) -> ProbeReport:
    if not settings.configured:
        return ProbeReport(
            reachable=False,
            error="未配置：需要 OPENAI_API_KEY 与 PRINTPILOT_LLM_MODEL。",
        )

    models = list_models(settings)
    report = ProbeReport(
        reachable=True,
        models=models,
        model_listed=(settings.model in models) if models else None,
    )

    for mode in StructuredMode:
        trial = settings.model_copy(update={"structured_mode": mode, "max_repair_attempts": 0})

        toy = OpenAICompatibleClient(settings=trial)
        try:
            answer = toy.complete_structured(prompt=PROBE_PROMPT, schema=ProbeAnswer)
        except LLMError as exc:
            report.modes.append(
                ModeResult(
                    mode=mode,
                    schema_name="ProbeAnswer",
                    ok=False,
                    detail=_short(str(exc)),
                    latency_ms=toy.usage.latency_ms,
                )
            )
        else:
            # Parsing and validating is not the same as answering. A provider that
            # returns well-formed JSON with invented values is a distinct problem.
            faithful = answer.verdict.strip().lower() == "ok" and answer.count == 3
            report.modes.append(
                ModeResult(
                    mode=mode,
                    schema_name="ProbeAnswer",
                    ok=True,
                    detail="" if faithful else "schema 通过但取值与要求不符",
                    latency_ms=toy.usage.latency_ms,
                )
            )

        real = OpenAICompatibleClient(settings=trial)
        try:
            real.complete_structured(prompt=REAL_PROMPT, schema=DiagnosisResult)
        except LLMError as exc:
            report.modes.append(
                ModeResult(
                    mode=mode,
                    schema_name="DiagnosisResult",
                    ok=False,
                    detail=_short(str(exc)),
                    latency_ms=real.usage.latency_ms,
                )
            )
        else:
            report.modes.append(
                ModeResult(
                    mode=mode,
                    schema_name="DiagnosisResult",
                    ok=True,
                    latency_ms=real.usage.latency_ms,
                )
            )

    if not any(r.ok for r in report.modes):
        report.reachable = False
        report.error = next(
            (r.detail for r in report.modes if r.detail), "所有结构化输出模式均失败。"
        )
    return report


def _short(message: str, limit: int = 160) -> str:
    collapsed = " ".join(message.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def format_probe(settings: LLMSettings, report: ProbeReport) -> str:
    lines: list[str] = []

    if report.models:
        lines.append(f"可用模型：共 {len(report.models)} 个")
        if report.model_listed is False:
            lines.append(f"  ⚠ 当前 model={settings.model!r} 不在列表中")
        elif report.model_listed:
            lines.append(f"  ✓ {settings.model} 在列表中")
    else:
        lines.append("可用模型：端点未提供 /v1/models（不影响使用）")

    lines.append("")
    lines.append("结构化输出实测（ProbeAnswer=玩具 schema，DiagnosisResult=管线真实 schema）：")
    for result in report.modes:
        mark = "✓" if result.ok else "✗"
        note = f"  {result.detail}" if result.detail else ""
        lines.append(
            f"  {mark} {result.mode.value:<12} {result.schema_name:<16}"
            f"{result.latency_ms:>7.0f} ms{note}"
        )

    lines.append("")
    if report.best_mode:
        lines.append(f"建议 PRINTPILOT_LLM_STRUCTURED_MODE={report.best_mode.value}")
        lines.append("（依据真实 schema 的结果选定；玩具 schema 通过不足以采信。）")
    else:
        lines.append(f"不可用：{report.error}")
    return "\n".join(lines)
