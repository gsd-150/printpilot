"""Run accounting.

Token spend, schema-violation rate and wall time are reported next to accuracy
because a configuration that wins by 2 points at four times the cost is not
obviously a win — that trade-off is the kind of thing an ablation is for.

Deliberately duck-typed. Anything carrying ``usage`` / ``call_count`` /
``schema_violations`` is accounted for; the rules baseline carries none of them and
is reported as free, which it is.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class RunCost(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: Summed across workers, so under concurrency this exceeds elapsed wall time.
    #: It measures work done, not how long you waited.
    api_seconds: float = 0.0
    schema_violations: int = 0
    repair_attempts: int = 0
    transport_failures: int = 0
    wall_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def per_case(self, n: int) -> float:
        return self.total_tokens / n if n else 0.0

    @property
    def violation_rate(self) -> float:
        return self.schema_violations / self.calls if self.calls else 0.0

    @property
    def speedup(self) -> float:
        """How much the concurrency actually bought, measured rather than assumed."""
        return self.api_seconds / self.wall_seconds if self.wall_seconds else 1.0


def collect_cost(diagnoser: Any, wall_seconds: float) -> RunCost:
    """Read whatever accounting a diagnoser happens to expose."""
    client = getattr(diagnoser, "client", None)
    usage = getattr(client, "usage", None)
    return RunCost(
        calls=int(getattr(client, "call_count", 0)),
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0)),
        completion_tokens=int(getattr(usage, "completion_tokens", 0)),
        api_seconds=float(getattr(usage, "latency_ms", 0.0)) / 1000.0,
        schema_violations=int(getattr(client, "schema_violations", 0)),
        repair_attempts=int(getattr(client, "repair_attempts", 0)),
        transport_failures=int(getattr(diagnoser, "failures", 0)),
        wall_seconds=wall_seconds,
    )


def format_cost(cost: RunCost, n: int) -> str:
    if cost.calls == 0:
        return f"  成本                无 API 调用（耗时 {cost.wall_seconds:.1f}s）"
    lines = [
        f"  调用次数            {cost.calls}",
        f"  token               {cost.total_tokens}"
        f"（输入 {cost.prompt_tokens} / 输出 {cost.completion_tokens}）"
        f"，每案例 {cost.per_case(n):.0f}",
        f"  耗时                实际 {cost.wall_seconds:.1f}s，"
        f"API 累计 {cost.api_seconds:.1f}s，加速比 {cost.speedup:.1f}×",
        f"  schema 违规         {cost.schema_violations}"
        f"（{cost.violation_rate:.1%}），修复重试 {cost.repair_attempts}",
    ]
    if cost.transport_failures:
        lines.append(f"  调用失败弃权        {cost.transport_failures}")
    return "\n".join(lines)
