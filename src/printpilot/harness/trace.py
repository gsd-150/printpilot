"""Full-chain tracing.

The claim this exists to support is "I can find out why it did that". Without a
record of what each step saw and produced, a wrong answer three configurations ago
is unrecoverable — you can re-run it, but re-running a non-deterministic model
answers a different question than the one you asked.

What each event records is chosen so a case can be reconstructed without the
original inputs: which prompt version, which Skills were injected, which chunks
were retrieved, what the gate ruled and on which rule, how many tokens it cost.
The point is attribution, not volume — a trace nobody can read is a log file.

Thread-safe: the evaluation runner fans out across workers and every one of them
writes here.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

TRACES_ROOT = Path("traces")


class Step(StrEnum):
    PERCEPTION = "perception"
    ROUTING = "routing"
    RETRIEVAL = "retrieval"
    DIAGNOSIS = "diagnosis"
    DECISION = "decision"
    SAFETY = "safety"
    EXECUTION = "execution"
    QUALITY = "quality"
    REFLECTION = "reflection"


@dataclass(frozen=True)
class TraceEvent:
    case_id: str
    step: Step
    duration_ms: float
    detail: dict[str, Any]
    error: str = ""

    def as_json(self) -> str:
        return json.dumps(
            {
                "case_id": self.case_id,
                "step": self.step.value,
                "duration_ms": round(self.duration_ms, 2),
                "error": self.error,
                **self.detail,
            },
            ensure_ascii=False,
            default=str,
        )


@dataclass
class Tracer:
    """Collects events. One per run; shared across workers."""

    events: list[TraceEvent] = field(default_factory=list)
    enabled: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(
        self, case_id: str, step: Step, *, duration_ms: float = 0.0, error: str = "", **detail: Any
    ) -> None:
        if not self.enabled:
            return
        event = TraceEvent(
            case_id=case_id, step=step, duration_ms=duration_ms, detail=detail, error=error
        )
        with self._lock:
            self.events.append(event)

    @contextmanager
    def span(self, case_id: str, step: Step, **detail: Any) -> Iterator[dict[str, Any]]:
        """Time a step and record it, whether or not it raised.

        Yields a dict the body can add to, so a step can report what it produced
        rather than only what it was given. A failure is recorded too — a step that
        vanishes from the trace when it errors is the one you most needed to see.
        """
        extra: dict[str, Any] = {}
        started = time.perf_counter()
        error = ""
        try:
            yield extra
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.record(
                case_id,
                step,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error=error,
                **{**detail, **extra},
            )

    def for_case(self, case_id: str) -> list[TraceEvent]:
        with self._lock:
            return [e for e in self.events if e.case_id == case_id]

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            # Grouped by case, chronological within a case. Workers interleave, and
            # an interleaved trace is unreadable exactly when it is needed.
            ordered = sorted(self.events, key=lambda e: (e.case_id,))
            path.write_text("".join(e.as_json() + "\n" for e in ordered), encoding="utf-8")
        return path

    def replay(self, case_id: str) -> str:
        """Human-readable reconstruction of one case."""
        events = self.for_case(case_id)
        if not events:
            return f"案例 {case_id}：无 trace 记录"
        lines = [f"案例 {case_id} 全链路回放（{len(events)} 步）"]
        for event in events:
            mark = "✗" if event.error else " "
            lines.append(f" {mark} {event.step.value:<12} {event.duration_ms:>8.1f} ms")
            if event.error:
                lines.append(f"      错误：{event.error}")
            for key, value in event.detail.items():
                lines.append(f"      {key}: {value}")
        return "\n".join(lines)

    @property
    def total_ms(self) -> float:
        return sum(e.duration_ms for e in self.events)


#: A tracer that records nothing, for callers that do not want the overhead.
DISABLED = Tracer(enabled=False)
