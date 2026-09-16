"""badcase 归因表：把评测结论、每实例测试明细和 trajectory 合成一张按失败模式分类的表。

    PYTHONPATH=. .venv/bin/python -m agent.report --run-id s5-mine
    PYTHONPATH=. .venv/bin/python -m agent.report --run-id s5-mine --compare s5-baseline

产出写进 results/evaluation/<run-id>/attribution.json 和 attribution.md ——
harness 的 logs/ 在 .gitignore 里，随时会被清掉，归因结论必须住进 results/。

失败模式的骨架照 `11-CodingAgent项目执行计划.md` §六，另加两条：
  - 模式 1 拆成「根本没产出 patch」和「产出了但打不上」—— 前者是 Agent 自己停早了，后者是 apply_patch 的锅
  - harness 自己的 infra_failure / ambiguous 单列，那是环境的锅，不进上面几桶
决定、实测：docs/DESIGN-run.md §五
"""
import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent.run import REPO_ROOT_DIR

GOLD_RUN: Final[str] = "s1-gold-subset"
_LOG_ROOTS: Final[tuple[str, ...]] = ("logs/evaluation", "SWE-bench/logs/evaluation")

# 每个桶配一句改法方向。没有改法的桶（M0、E1、E2）写明「不是 Agent 的问题」
MODES: Final[dict[str, tuple[str, str]]] = {
    "resolved": ("解出来了", "—"),
    "M0_undecidable": ("实例本身不可判定（gold patch 也拿不到 resolved）",
                       "不是 Agent 的问题。进 KNOWN_BAD 剔除，并记录证据链"),
    "M1a_no_patch": ("根本没产出 patch（空 diff）",
                     "看 stop_reason：max_steps 说明步数不够或它在绕圈；finished 说明它自以为做完了 —— 要在 prompt 里加「空 diff 得零分」"),
    "M1b_patch_rejected": ("产出了 patch 但打不上",
                           "scaffold 问题：收紧「编辑前怎么看文件」；apply_patch 是 search/replace，理论上打不上只可能是 diff 提取出了问题"),
    "M2_fail_to_pass": ("打上了但 FAIL_TO_PASS 仍失败",
                        "最大的一桶，逐条读 trajectory：改了个像的 bug，或三处调用只改了一处"),
    "M3_regression": ("FAIL_TO_PASS 过了但 PASS_TO_PASS 挂",
                      "引入回归：让它提交前先跑邻近测试"),
    "E1_infra": ("harness 报 infra failure", "环境的锅，不是 Agent 的。重跑一次，仍然失败就单列"),
    "E2_ambiguous": ("harness 报 ambiguous failure", "环境的锅，不是 Agent 的。单列，不进上面几桶"),
    "missing": ("没有评测记录", "这条实例没跑，或 report.json 被清掉了"),
}


@dataclass
class Row:
    """归因表的一行：一条实例的结论 + 它是怎么跑的。"""

    instance_id: str
    mode: str
    stop_reason: str = ""
    steps: int = 0
    tool_errors: int = 0
    cost: float = 0.0
    patch_chars: int = 0
    f2p_failed: list[str] = field(default_factory=list)
    p2p_failed: list[str] = field(default_factory=list)


def find_eval_dir(run_id: str, root: Path = REPO_ROOT_DIR) -> Path | None:
    """评测日志可能在仓库根的 logs/ 下，也可能在 SWE-bench/logs/ 下，取决于当初在哪跑的。"""
    for candidate in _LOG_ROOTS:
        path = root / candidate / run_id
        if path.is_dir():
            return path
    return None


def load_instance_reports(eval_dir: Path) -> dict[str, dict]:
    """收集 <eval_dir>/<model>/<instance_id>/report.json，返回 {instance_id: 报告}。"""
    reports: dict[str, dict] = {}
    for path in sorted(eval_dir.glob("*/*/report.json")):
        content = json.loads(path.read_text(encoding="utf-8"))
        # 每份 report.json 是 {instance_id: {...}}，只有一个键
        for instance_id, body in content.items():
            reports[instance_id] = body
    return reports


def undecidable_ids(run_id: str = GOLD_RUN, root: Path = REPO_ROOT_DIR) -> set[str]:
    """gold patch 都拿不到 resolved 的实例。**区分模式 0 和模式 3 的唯一办法，就是先跑 gold。**"""
    results = root / "results" / "evaluation" / run_id / "results.json"
    if not results.is_file():
        return set()
    content = json.loads(results.read_text(encoding="utf-8"))
    return set(content.get("unresolved_ids", [])) | set(content.get("error_ids", []))


def classify(report: dict, instance_id: str, undecidable: set[str]) -> tuple[str, list[str], list[str]]:
    """把一份 report.json 归进一个桶，返回 (桶名, F2P 挂了哪些, P2P 挂了哪些)。

    顺序要紧：模式 0 必须先判 —— 它长得和模式 3 一模一样（都是 F2P 过、P2P 挂），但归因完全相反。
    """
    status = report.get("tests_status", {})
    f2p_failed = list(status.get("FAIL_TO_PASS", {}).get("failure", []))
    p2p_failed = list(status.get("PASS_TO_PASS", {}).get("failure", []))

    if report.get("resolved"):
        return "resolved", f2p_failed, p2p_failed
    if instance_id in undecidable:
        return "M0_undecidable", f2p_failed, p2p_failed
    if report.get("infra_failure"):
        return "E1_infra", f2p_failed, p2p_failed
    if report.get("patch_is_None") or not report.get("patch_exists", True):
        return "M1a_no_patch", f2p_failed, p2p_failed
    if not report.get("patch_successfully_applied", True):
        return "M1b_patch_rejected", f2p_failed, p2p_failed
    if f2p_failed:
        return "M2_fail_to_pass", f2p_failed, p2p_failed
    if p2p_failed:
        return "M3_regression", f2p_failed, p2p_failed
    return "E2_ambiguous", f2p_failed, p2p_failed


def build_rows(run_id: str, root: Path = REPO_ROOT_DIR) -> list[Row]:
    """把评测结论和 summary.json 合成归因表的行。没有 summary 的（如 mini baseline）只填评测那半边。"""
    eval_dir = find_eval_dir(run_id, root)
    if eval_dir is None:
        raise FileNotFoundError(f"找不到 {run_id} 的评测日志，试过 {_LOG_ROOTS}")

    reports = load_instance_reports(eval_dir)
    undecidable = undecidable_ids(root=root)

    summary_path = root / "results" / "inference" / run_id / "summary.json"
    runs: dict[str, dict] = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        runs = {item["instance_id"]: item for item in summary.get("instances", [])}

    instance_ids = sorted(set(reports) | set(runs))
    rows: list[Row] = []
    for instance_id in instance_ids:
        report = reports.get(instance_id)
        if report is None:
            mode, f2p, p2p = "missing", [], []
        else:
            mode, f2p, p2p = classify(report, instance_id, undecidable)
        run = runs.get(instance_id, {})
        rows.append(Row(
            instance_id=instance_id, mode=mode,
            stop_reason=run.get("stop_reason", ""), steps=run.get("steps", 0),
            tool_errors=run.get("tool_errors", 0), cost=run.get("cost", 0.0),
            patch_chars=run.get("patch_chars", 0), f2p_failed=f2p, p2p_failed=p2p,
        ))
    return rows


def render(run_id: str, rows: list[Row], compare: tuple[str, list[Row]] | None = None) -> str:
    """把归因表渲染成 markdown。表里只放数，名字列在下面 —— 一行一实例的表在 25 条上就读不动了。"""
    counts = Counter(row.mode for row in rows)
    other = Counter(row.mode for row in compare[1]) if compare else None

    lines = [f"# badcase 归因表 · `{run_id}`", "",
             f"共 {len(rows)} 条实例"
             + (f"，对照 `{compare[0]}`（{len(compare[1])} 条）" if compare else ""), ""]

    header = "| 模式 | 是什么 | 本次 |" + (f" `{compare[0]}` |" if compare else "") + " 修法方向 |"
    lines += [header, "| --- | --- | ---: |" + (" ---: |" if compare else "") + " --- |"]
    for mode, (what, fix) in MODES.items():
        if not counts[mode] and not (other and other[mode]):
            continue
        row = f"| `{mode}` | {what} | **{counts[mode]}** |"
        if other is not None:
            row += f" {other[mode]} |"
        lines.append(f"{row} {fix} |")

    resolved = counts["resolved"]
    gradable = len(rows) - counts["M0_undecidable"] - counts["E1_infra"] - counts["E2_ambiguous"]
    lines += ["", f"**resolved {resolved}/{len(rows)}**"
              + (f"；剔除不可判定与环境故障后 {resolved}/{gradable}" if gradable != len(rows) else ""), ""]

    # 停止原因 × 结论：这张交叉表才看得出「是步数不够，还是它自以为做完了」
    if any(row.stop_reason for row in rows):
        pairs = Counter((row.stop_reason, row.mode) for row in rows)
        lines += ["## 停止原因 × 结论", "", "| stop_reason | 结论 | 条数 |", "| --- | --- | ---: |"]
        lines += [f"| `{stop}` | `{mode}` | {count} |" for (stop, mode), count in sorted(pairs.items())]
        lines.append("")

    lines += ["## 逐条", "", "| 实例 | 结论 | stop_reason | 步数 | 工具错 | $ | patch | 挂了的测试 |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for row in rows:
        failed = ", ".join((row.f2p_failed + row.p2p_failed)[:2]) or "—"
        lines.append(f"| `{row.instance_id}` | `{row.mode}` | `{row.stop_reason or '—'}` | {row.steps} "
                     f"| {row.tool_errors} | {row.cost:.4f} | {row.patch_chars} | {failed} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--compare", default=None, help="并排对照的另一个 run-id（通常是 baseline）")
    args = parser.parse_args(argv)

    rows = build_rows(args.run_id)
    compare = (args.compare, build_rows(args.compare)) if args.compare else None

    out_dir = REPO_ROOT_DIR / "results" / "evaluation" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "attribution.json").write_text(
        json.dumps({"run_id": args.run_id,
                    "counts": dict(Counter(row.mode for row in rows)),
                    "rows": [vars(row) for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    text = render(args.run_id, rows, compare)
    (out_dir / "attribution.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"written: {out_dir / 'attribution.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
