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


def _run_eval(root: Path, split_name: str, diagnoser_name: str) -> int:
    from printpilot.diagnosis import diagnose
    from printpilot.eval import format_report, run_split
    from printpilot.simulator import Split

    if not (root / split_name / "cases.jsonl").exists():
        print(f"找不到数据集：{root}/{split_name}/。先运行 `printpilot dataset`。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    if diagnoser_name != "rules":
        print(f"诊断配置 `{diagnoser_name}` 尚未实现，计划在 M4 后半。", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED

    report = run_split(root, Split(split_name), diagnose, name=diagnoser_name)
    print(format_report(report))
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

    p_llm = sub.add_parser("llm-check", help="实测所配置端点的连通性与结构化输出能力")
    p_llm.add_argument("--models", action="store_true", help="打印完整可用模型列表")

    p_skills = sub.add_parser("skills", help="Agent Skills 注册表工具 (M5)")
    p_skills.add_argument("action", choices=["list", "validate", "route"])

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
            return _run_eval(args.data, args.split, args.diagnoser)
        case "llm-check":
            return _run_llm_check(args.models)
        case "skills":
            return _not_implemented(f"skills {args.action}", "M5")
        case _:  # pragma: no cover - argparse rejects unknown commands first
            parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
