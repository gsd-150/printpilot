"""Cross-platform entry point.

Deliberately argparse rather than a CLI framework: it keeps the runtime dependency
set at exactly one package (pydantic), so ``uv run printpilot`` works on a clean
machine. Windows has no GNU make, so this — not a Makefile — is the reproduction
path documented in the README.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from printpilot import __version__
from printpilot.harness import DEFAULT_WORKERS
from printpilot.simulator import DEFAULT_MASTER_SEED, write_dataset
from printpilot.status import MILESTONES, completion_line

EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 2

DEFAULT_DATASET_ROOT = Path("datasets")


def _print_info() -> int:
    print(f"PrintPilot {__version__}")
    print("FDM 打印过程异常诊断与安全动作决策系统")
    print()
    print("边界：合成遥测环境，虚拟传感器，非真实产线，不控制实机。")
    print()
    print(completion_line())
    for m in MILESTONES:
        print(f"  {m.status.marker} {m.id}  {m.title}")
        print(f"        验收：{m.acceptance}")
    return EXIT_OK


def _run_dataset(root: Path, seed: int) -> int:
    manifest = write_dataset(root, seed)
    counts = manifest["counts"]
    assert isinstance(counts, dict)
    total = sum(counts.values())
    print(f"已生成 {total} 条合成案例 → {root}/  (master_seed={seed})")
    for split, n in counts.items():
        print(f"  {split:<10} {n:>4} 条")
    print(f"清单：{root / 'manifest.json'}")
    print("提示：cases.jsonl 与 labels.jsonl 分开存放，标签不应进入 Agent 上下文。")
    return EXIT_OK


def _build_diagnoser(name: str, prompt: str | None = None) -> tuple[object, str] | None:
    """Returns (callable, display name), or None if the configuration is unusable."""
    from printpilot.diagnosis import diagnose

    if name == "rules":
        return diagnose, "rules"

    if name in {"llm", "llm+skills"}:
        from printpilot.diagnosis.llm import DEFAULT_PROMPT, LLMDiagnoser
        from printpilot.llm import OpenAICompatibleClient, load_settings
        from printpilot.prompts import load_prompt
        from printpilot.skills_runtime import SkillRegistry

        settings = load_settings()
        if not settings.configured:
            print(
                "LLM 未配置：需要 .env 中的 OPENAI_API_KEY 与 PRINTPILOT_LLM_MODEL。",
                file=sys.stderr,
            )
            return None

        registry: SkillRegistry | None = None
        if name == "llm+skills":
            registry = SkillRegistry.load()
            if registry.errors:
                print("Skills 未通过校验，先修复后再消融。", file=sys.stderr)
                return None

        diagnoser = LLMDiagnoser(
            client=OpenAICompatibleClient(settings=settings),
            prompt=load_prompt(prompt or DEFAULT_PROMPT),
            skills=registry,
        )
        return diagnoser, f"{diagnoser.name}|{settings.model}"

    print(f"诊断配置 `{name}` 尚未实现。", file=sys.stderr)
    return None


def _run_eval(
    root: Path,
    split_name: str,
    diagnoser_name: str,
    limit: int | None,
    prompt: str | None = None,
    workers: int | None = None,
    save: str | None = None,
) -> int:
    from printpilot.eval import format_report, run_split
    from printpilot.eval.runner import stderr_progress
    from printpilot.harness import format_cost
    from printpilot.simulator import Split

    if not (root / split_name / "cases.jsonl").exists():
        print(f"找不到数据集：{root}/{split_name}/。先运行 `printpilot dataset`。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    built = _build_diagnoser(diagnoser_name, prompt)
    if built is None:
        return EXIT_NOT_IMPLEMENTED
    diagnoser, display = built

    result = run_split(
        root,
        Split(split_name),
        diagnoser,  # type: ignore[arg-type]
        name=display,
        limit=limit,
        workers=1 if diagnoser_name == "rules" else workers,
        progress=stderr_progress if diagnoser_name != "rules" else None,
    )
    print(format_report(result.report))
    print(format_cost(result.cost, result.report.n))

    if save:
        from printpilot.eval import build_record, save_record

        record = build_record(
            name=save,
            report=result.report,
            predictions=result.predictions,
            cost=result.cost,
            model=_model_name(diagnoser_name),
            prompt=prompt or "",
        )
        path = save_record(record)
        print(f"\n逐案例结果 → {path}")
    return EXIT_OK


def _model_name(diagnoser_name: str) -> str:
    """Recorded so a later comparison can refuse runs made with different models.

    Empty for the rules arm — it uses no model, and a placeholder like "n/a" would
    read as a *different* model and block the rules-vs-LLM comparison, which is the
    one the whole ablation is built around.
    """
    if diagnoser_name == "rules":
        return ""
    from printpilot.llm import load_settings

    return load_settings().model


def _run_compare(path_a: Path, path_b: Path) -> int:
    from printpilot.eval import IncomparableRunsError, format_comparison, load_record

    try:
        print(format_comparison(load_record(path_a), load_record(path_b)))
    except IncomparableRunsError as exc:
        print(f"无法比较：{exc}", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    return EXIT_OK


def _run_llm_check(show_models: bool) -> int:
    from printpilot.llm import load_settings
    from printpilot.llm.probe import format_probe, list_models, probe

    settings = load_settings()
    print(f"配置：{settings.describe()}\n")

    if not settings.api_key:
        print("需要在 .env 中填写 OPENAI_API_KEY。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    # Listing models is how you find out what to put in PRINTPILOT_LLM_MODEL, so
    # it must work before that variable is set.
    if not settings.model:
        available = list_models(settings)
        if not available:
            print("端点未提供 /v1/models，请查阅供应商文档后填写模型 id。", file=sys.stderr)
            return EXIT_NOT_IMPLEMENTED
        print(f"端点可用模型共 {len(available)} 个：")
        for name in available:
            print(f"  {name}")
        print("\n在 .env 中设置 PRINTPILOT_LLM_MODEL=<其中之一> 后重新运行。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    report = probe(settings)
    print(format_probe(settings, report))
    if show_models and report.models:
        print("\n完整模型列表：")
        for name in report.models:
            print(f"  {name}")
    return EXIT_OK if report.best_mode else EXIT_NOT_IMPLEMENTED


def _run_skills(action: str, case_id: str | None, root: Path | None) -> int:
    from printpilot.skills_runtime import Severity, SkillRegistry

    registry = SkillRegistry.load(root)
    if not registry.skills and not registry.parse_failures:
        print("未发现任何 Skill。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    match action:
        case "list":
            print(f"{'名称':<28}{'版本':<10}{'领域':<18}触发特征")
            for skill in registry.skills:
                meta = skill.meta
                print(
                    f"{meta.name:<28}{meta.version:<10}{meta.domain:<18}{', '.join(meta.triggers)}"
                )
            return EXIT_OK

        case "validate":
            issues = registry.validate()
            if not issues:
                print(f"{len(registry.skills)} 个 Skill 全部通过校验。")
                return EXIT_OK
            for issue in issues:
                print(str(issue), file=sys.stderr)
            errors = sum(1 for i in issues if i.severity is Severity.ERROR)
            print(f"\n{len(issues)} 项问题（{errors} 个错误）。", file=sys.stderr)
            # Warnings alone must not fail CI; errors must.
            return EXIT_NOT_IMPLEMENTED if errors else EXIT_OK

        case "route":
            return _route_case(registry, case_id)

    return EXIT_NOT_IMPLEMENTED  # pragma: no cover - argparse restricts the choices


def _route_case(registry: object, case_id: str | None) -> int:
    from printpilot.perception import perceive
    from printpilot.simulator import Split, load_cases

    if case_id is None:
        print("`skills route` 需要 --case <case_id>。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    split = Split(case_id.split("-", 1)[0])
    case = next((c for c in load_cases(DEFAULT_DATASET_ROOT, split) if c.case_id == case_id), None)
    if case is None:
        print(f"找不到案例 {case_id}。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    report = perceive(case.telemetry, material=case.material.value)
    matches = registry.route(report)  # type: ignore[attr-defined]
    print(f"案例 {case_id}（材料 {case.material.value}）")
    print(f"越界特征：{', '.join(f.name for f in report.features if f.exceeded) or '无'}")
    if report.uncomputable_features:
        print(f"无法测量：{', '.join(report.uncomputable_features)}")
    print()
    if not matches:
        print("没有 Skill 被选中。")
        return EXIT_OK
    for rank, match in enumerate(matches, start=1):
        flag = "（降级：缺 " + ", ".join(match.missing_optional) + "）" if match.degraded else ""
        print(f"  {rank}. {match.skill.name:<28} 得分 {match.score:.3f}{flag}")
        print(f"     命中触发：{', '.join(match.satisfied_triggers)}")
    return EXIT_OK


def _not_implemented(command: str, milestone: str) -> int:
    print(f"`printpilot {command}` 尚未实现，计划在 {milestone}。", file=sys.stderr)
    print("当前进度见 `printpilot info`。", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printpilot",
        description="FDM 打印过程异常诊断与安全动作决策系统",
    )
    parser.add_argument("--version", action="version", version=f"printpilot {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("info", help="显示项目边界与里程碑完成度")

    p_dataset = sub.add_parser("dataset", help="生成合成遥测数据集")
    p_dataset.add_argument("--seed", type=int, default=DEFAULT_MASTER_SEED)
    p_dataset.add_argument("--out", type=Path, default=DEFAULT_DATASET_ROOT)

    p_eval = sub.add_parser("eval", help="运行评测")
    p_eval.add_argument("--split", choices=["dev", "holdout", "challenge"], default="dev")
    p_eval.add_argument("--diagnoser", default="rules", help="rules | llm | llm+rag | llm+skills")
    p_eval.add_argument("--data", type=Path, default=DEFAULT_DATASET_ROOT)
    p_eval.add_argument(
        "--limit", type=int, default=None, help="等距抽样 N 条，用于提示词迭代（不可与全量比较）"
    )
    p_eval.add_argument(
        "--prompt", default=None, help="提示词版本，如 diagnosis/v2_rule_out（默认取基线版）"
    )
    p_eval.add_argument(
        "--workers", type=int, default=None, help=f"并发上限，默认 {DEFAULT_WORKERS}"
    )
    p_eval.add_argument(
        "--save", default=None, help="把逐案例结果存为 evals/runs/<名称>.json，供配对比较"
    )

    p_compare = sub.add_parser("compare", help="两次运行的配对比较（McNemar）与错误归因")
    p_compare.add_argument("run_a", type=Path)
    p_compare.add_argument("run_b", type=Path)

    p_llm = sub.add_parser("llm-check", help="实测所配置端点的连通性与结构化输出能力")
    p_llm.add_argument("--models", action="store_true", help="打印完整可用模型列表")

    p_skills = sub.add_parser("skills", help="Agent Skills 注册表工具")
    p_skills.add_argument("action", choices=["list", "validate", "route"])
    p_skills.add_argument("--case", default=None, help="route 用：案例 id，如 dev-0000")
    p_skills.add_argument("--root", type=Path, default=None, help="Skills 目录，默认 skills/")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    match args.command:
        case "info" | None:
            return _print_info()
        case "dataset":
            return _run_dataset(args.out, args.seed)
        case "eval":
            return _run_eval(
                args.data,
                args.split,
                args.diagnoser,
                args.limit,
                args.prompt,
                args.workers,
                args.save,
            )
        case "compare":
            return _run_compare(args.run_a, args.run_b)
        case "llm-check":
            return _run_llm_check(args.models)
        case "skills":
            return _run_skills(args.action, args.case, args.root)
        case _:  # pragma: no cover - argparse rejects unknown commands first
            parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
