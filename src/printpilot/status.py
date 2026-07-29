"""Milestone state, kept in code so ``printpilot info`` reports it at runtime.

The README quotes this table. Keeping the source of truth executable means the
stated completion level cannot drift away from what actually ships — a milestone
is only VERIFIED once its acceptance command genuinely passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MilestoneStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"

    @property
    def marker(self) -> str:
        return {"planned": "[ ]", "in_progress": "[~]", "verified": "[x]"}[self.value]


@dataclass(frozen=True)
class Milestone:
    id: str
    title: str
    status: MilestoneStatus
    acceptance: str


MILESTONES: tuple[Milestone, ...] = (
    Milestone(
        id="M1",
        title="工程骨架、schemas、CI、离线 mock LLM",
        status=MilestoneStatus.VERIFIED,
        acceptance="ruff + mypy + pytest 全绿",
    ),
    Milestone(
        id="M2",
        title="LangGraph 选型验证与节点契约校验",
        status=MilestoneStatus.VERIFIED,
        acceptance="docs/decisions/0001 + tests/test_langgraph_smoke.py",
    ),
    Milestone(
        id="M3",
        title="合成遥测环境：故障注入 + 虚拟传感器 + 独立质量评估器",
        status=MilestoneStatus.VERIFIED,
        acceptance="printpilot dataset 产出 160 条 + manifest",
    ),
    Milestone(
        id="M4",
        title="Perception + 规则基线 + 评测体系（LLM 诊断节点待接入）",
        status=MilestoneStatus.IN_PROGRESS,
        acceptance="printpilot eval --split dev 输出基线指标",
    ),
    Milestone(
        id="M5",
        title="2 个 Skill + 注册机制 + 接入诊断，dev 全量消融完成",
        status=MilestoneStatus.VERIFIED,
        acceptance="printpilot skills validate 能拦住坏 Skill",
    ),
    Milestone(
        id="M6",
        title="单向量后端 + 10–15 张知识卡 + 检索评测",
        status=MilestoneStatus.PLANNED,
        acceptance="Hit@k / MRR 为实测值",
    ),
    Milestone(
        id="M7",
        title="Decision + SafetyGate + Execution（闭环 Demo 待接）",
        status=MilestoneStatus.IN_PROGRESS,
        acceptance="test_safety_gate.py 全绿；闭环 Demo 可跑",
    ),
    Milestone(
        id="M8",
        title="消融、Trace、README、Demo 录制",
        status=MilestoneStatus.PLANNED,
        acceptance="五档消融表填满实测值",
    ),
)


def verified_count() -> int:
    return sum(1 for m in MILESTONES if m.status is MilestoneStatus.VERIFIED)


def completion_line() -> str:
    return f"当前完成度：{verified_count()}/{len(MILESTONES)} 里程碑已验证"
