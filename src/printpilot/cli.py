"""Cross-platform entry point.

Deliberately argparse rather than a CLI framework: it keeps the runtime dependency
set at exactly one package (pydantic), so ``uv run printpilot`` works on a clean
machine. Windows has no GNU make, so this — not a Makefile — is the reproduction
path documented in the README.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from printpilot import __version__
from printpilot.harness import DEFAULT_WORKERS
from printpilot.simulator import DEFAULT_MASTER_SEED, write_dataset
from printpilot.status import MILESTONES, completion_line

if TYPE_CHECKING:
    from printpilot.decision.llm import LLMDecider
    from printpilot.loop import LoopResult
    from printpilot.reflection import Reflector

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

    if name.startswith("llm"):
        from printpilot.diagnosis.llm import DEFAULT_PROMPT, LLMDiagnoser
        from printpilot.harness import Tracer
        from printpilot.llm import OpenAICompatibleClient, load_embedding_settings, load_settings
        from printpilot.prompts import load_prompt
        from printpilot.rag import CachedEmbedder, KnowledgeStore, OpenAIEmbedder, clean, load_cards
        from printpilot.skills_runtime import SkillRegistry

        arms = set(name.split("+"))
        if not arms <= {"llm", "rag", "skills"}:
            print(f"诊断配置 `{name}` 尚未实现。", file=sys.stderr)
            return None

        settings = load_settings()
        if not settings.configured:
            print(
                "LLM 未配置：需要 .env 中的 OPENAI_API_KEY 与 PRINTPILOT_LLM_MODEL。",
                file=sys.stderr,
            )
            return None

        registry: SkillRegistry | None = None
        if "skills" in arms:
            registry = SkillRegistry.load()
            if registry.errors:
                print("Skills 未通过校验，先修复后再消融。", file=sys.stderr)
                return None

        store: KnowledgeStore | None = None
        if "rag" in arms:
            # Embeddings may live on a different host than chat — see
            # ``load_embedding_settings``. Cached because the corpus and most
            # queries repeat across runs and the endpoint meters every request.
            embedder = CachedEmbedder(OpenAIEmbedder(settings=load_embedding_settings()))
            store = KnowledgeStore(embedder=embedder)
            store.build(clean(load_cards()).kept)

        diagnoser = LLMDiagnoser(
            client=OpenAICompatibleClient(settings=settings),
            prompt=load_prompt(prompt or DEFAULT_PROMPT),
            skills=registry,
            knowledge=store,
            tracer=Tracer(),
        )
        return diagnoser, f"{diagnoser.name}|{settings.model}"

    print(f"诊断配置 `{name}` 尚未实现。", file=sys.stderr)
    return None


def _build_reflector() -> Reflector | None:
    """Mirrors ``_build_diagnoser``'s contract: ``None`` means unusable config."""
    from printpilot.llm import OpenAICompatibleClient, load_settings
    from printpilot.reflection import Reflector

    settings = load_settings()
    if not settings.configured:
        print(
            "LLM 未配置：需要 .env 中的 OPENAI_API_KEY 与 PRINTPILOT_LLM_MODEL。",
            file=sys.stderr,
        )
        return None
    return Reflector(client=OpenAICompatibleClient(settings=settings))


def _build_decider() -> LLMDecider | None:
    """Mirrors ``_build_diagnoser``'s contract: ``None`` means unusable config."""
    from printpilot.decision.llm import LLMDecider
    from printpilot.llm import OpenAICompatibleClient, load_settings

    settings = load_settings()
    if not settings.configured:
        print(
            "LLM 未配置：需要 .env 中的 OPENAI_API_KEY 与 PRINTPILOT_LLM_MODEL。",
            file=sys.stderr,
        )
        return None
    return LLMDecider(client=OpenAICompatibleClient(settings=settings))


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

        tracer = getattr(diagnoser, "tracer", None)
        if tracer is not None and tracer.events:
            from printpilot.harness import TRACES_ROOT

            trace_path = tracer.write(TRACES_ROOT / f"{save}.jsonl")
            print(f"全链路 trace（{len(tracer.events)} 步）→ {trace_path}")
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


def _run_rag(action: str, use_mock: bool) -> int:
    from printpilot.llm import load_embedding_settings
    from printpilot.rag import (
        CachedEmbedder,
        DeterministicEmbedder,
        Embedder,
        KnowledgeStore,
        OpenAIEmbedder,
        clean,
        evaluate,
        load_cards,
        load_queries,
    )

    cards = load_cards()
    if not cards:
        print("知识库为空。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    report = clean(cards)
    print(report.format())
    print()

    if action == "clean":
        return EXIT_OK

    embedder: Embedder
    if use_mock:
        embedder = DeterministicEmbedder()
    else:
        settings = load_embedding_settings()
        if not settings.api_key:
            print(
                "需要 PRINTPILOT_EMBEDDING_API_KEY（或共用的 OPENAI_API_KEY）；"
                "或加 --mock 用非语义 embedder 打通链路。",
                file=sys.stderr,
            )
            return EXIT_NOT_IMPLEMENTED
        embedder = CachedEmbedder(OpenAIEmbedder(settings=settings))

    store = KnowledgeStore(embedder=embedder)
    print(f"已索引 {store.build(report.kept)} 条卡片（embedder={embedder.name}）")
    print()

    if action == "build":
        return EXIT_OK

    print(evaluate(store, load_queries()).format())
    return EXIT_OK


def _run_loop(seed: str, reflect: bool = False, decider: str = "rules") -> int:
    from printpilot.loop import LoopOutcome, demo_families, run_round

    # LLM arms are built before any round runs: a misconfigured flag should
    # cost zero simulations, not fail after five of them.
    reflector: Reflector | None = None
    if reflect:
        reflector = _build_reflector()
        if reflector is None:
            return EXIT_NOT_IMPLEMENTED

    pipeline: object | None = None
    llm_decider: LLMDecider | None = None
    if decider == "llm":
        llm_decider = _build_decider()
        if llm_decider is None:
            return EXIT_NOT_IMPLEMENTED
        from printpilot.workflow import build_pipeline

        pipeline = build_pipeline(decider=llm_decider)

    outcomes: dict[LoopOutcome, int] = {}
    gate: dict[str, int] = {}
    for family in demo_families():
        result = run_round(
            family, case_id=f"demo-{family.fault.value}", seed=seed, pipeline=pipeline
        )
        print(result.summary())
        print(f"  真实故障 {family.fault.value}")
        if reflector is not None:
            _reflect_round(reflector, result)
        print()
        outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
        ruling = result.verdict.decision.value
        gate[ruling] = gate.get(ruling, 0) + 1

    print("汇总：" + "，".join(f"{k.value} {v}" for k, v in sorted(outcomes.items())))
    print("质量由独立评估器判定——它只看遥测，不知道注入了什么故障、也不知道改了什么。")
    if llm_decider is not None:
        tally = "，".join(f"{k} {v}" for k, v in sorted(gate.items()))
        print(f"门禁对 LLM 提案的裁决：{tally}——提议与放行之间隔着这道闸。")
        if llm_decider.failures:
            print(f"决策调用失败 {llm_decider.failures} 轮（已自动升级人工）。", file=sys.stderr)
    if reflector is not None:
        if reflector.failures:
            print(f"复盘失败 {reflector.failures} 轮（传输错误，未产卡片）。", file=sys.stderr)
        print("候选卡片在 knowledge/candidate_cases/ 隔离区，审批流程见 knowledge/README.md。")
    return EXIT_OK


def _reflect_round(reflector: Reflector, result: LoopResult) -> None:
    """Reflection sees ``result`` only — the injected fault printed above it
    goes to the human watching the demo, never into the model's record."""
    from printpilot.reflection import write_candidate

    card = reflector(result)
    if card is None:
        print("  复盘    调用失败，本轮无候选卡片", file=sys.stderr)
        return
    path = write_candidate(card)
    if path is None:
        print(f"  复盘    候选已存在（{card.id}），未覆盖")
    else:
        print(f"  复盘    候选卡片 → {path}")


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
    p_eval.add_argument(
        "--diagnoser",
        default="rules",
        help="rules | llm | llm+rag | llm+skills | llm+rag+skills",
    )
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

    p_rag = sub.add_parser("rag", help="知识库：清洗、索引、检索评测")
    p_rag.add_argument("action", choices=["clean", "build", "eval"])
    p_rag.add_argument(
        "--mock", action="store_true", help="用非语义 embedder（仅打通链路，指标不可引用）"
    )

    p_loop = sub.add_parser("loop", help="闭环演示：诊断→决策→门禁→执行→重打印→独立评分")
    p_loop.add_argument("--seed", default="demo", help="仿真种子，两轮共用以隔离参数效应")
    p_loop.add_argument(
        "--reflect",
        action="store_true",
        help="每轮 LLM 复盘产出候选知识卡片，只写 knowledge/candidate_cases/ 隔离区",
    )
    p_loop.add_argument(
        "--decider",
        choices=["rules", "llm"],
        default="rules",
        help="决策节点实现；llm 为消融臂——LLM 提议，门禁照常裁决并统计拦截",
    )

    p_llm = sub.add_parser("llm-check", help="实测所配置端点的连通性与结构化输出能力")
    p_llm.add_argument("--models", action="store_true", help="打印完整可用模型列表")

    p_skills = sub.add_parser("skills", help="Agent Skills 注册表工具")
    p_skills.add_argument("action", choices=["list", "validate", "route"])
    p_skills.add_argument("--case", default=None, help="route 用：案例 id，如 dev-0000")
    p_skills.add_argument("--root", type=Path, default=None, help="Skills 目录，默认 skills/")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # This tool prints Chinese. A Windows stream outside a UTF-8 code page —
    # GitHub's runners pipe stdout as cp1252 — cannot encode it and dies with
    # UnicodeEncodeError, which is how the first public CI run failed. A CJK
    # Windows install masks this (GBK encodes the output), so it never shows
    # on the machine the tool was written on. Reconfigure rather than crash.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() not in (
            "utf-8",
            "utf8",
        ):
            stream.reconfigure(encoding="utf-8")

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
        case "rag":
            return _run_rag(args.action, args.mock)
        case "loop":
            return _run_loop(args.seed, args.reflect, args.decider)
        case "llm-check":
            return _run_llm_check(args.models)
        case "skills":
            return _run_skills(args.action, args.case, args.root)
        case _:  # pragma: no cover - argparse rejects unknown commands first
            parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
