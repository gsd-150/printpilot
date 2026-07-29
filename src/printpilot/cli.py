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

from printpilot import __version__
from printpilot.status import MILESTONES, completion_line

EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 2


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

    p_dataset = sub.add_parser("dataset", help="生成合成遥测数据集 (M3)")
    p_dataset.add_argument("--seed", type=int, default=42)

    p_eval = sub.add_parser("eval", help="运行评测与消融 (M4)")
    p_eval.add_argument("--split", choices=["dev", "holdout", "challenge"], default="dev")
    p_eval.add_argument("--ablation", default="none")

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
            return _not_implemented("dataset", "M3")
        case "eval":
            return _not_implemented("eval", "M4")
        case "skills":
            return _not_implemented(f"skills {args.action}", "M5")
        case _:  # pragma: no cover - argparse rejects unknown commands first
            parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
