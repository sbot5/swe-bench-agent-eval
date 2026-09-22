"""P4 §2.1 ⒞「三段各几轮」的 $0 数据底：从已落盘轨迹算首刀轮号分布。

只读 results/inference/，不调模型、不改 agent/。口径：
- 一步一个工具调用（StepRecord.tool_name），首刀 = 最小的 tool_name == "apply_patch" 的 index
- B 组 = 该跑里 apply_patch 次数 > 0 的实例；A 组 = 0 次（㊱ 的那个二元失败模式）
- 照 ㊾：任何新量先看它自己的跑间方差，所以每一跑单独报、不合并

用法：python3 scripts/stage_budget.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

RUNS = ["p2-mine", "p2-rerun"]  # 只有这两跑是 25 条全跑，同时含 A 组与 B 组
ROOT = Path(__file__).resolve().parent.parent
INFER = ROOT / "results" / "inference"


def load(run: str) -> dict[str, dict]:
    out = {}
    for path in sorted((INFER / run).glob("*.traj.json")):
        data = json.loads(path.read_text())
        out[data["instance_id"]] = data
    return out


def first_index(steps: list[dict], name: str) -> int | None:
    for step in steps:
        if step.get("tool_name") == name:
            return step["index"]
    return None


def main() -> None:
    per_run: dict[str, dict[str, dict]] = {}
    for run in RUNS:
        rows = {}
        for instance_id, traj in load(run).items():
            steps = traj["steps"]
            rows[instance_id] = {
                "steps": len(steps),
                "first_patch": first_index(steps, "apply_patch"),
                "first_python": first_index(steps, "run_python"),
                "first_tests": first_index(steps, "run_tests"),
                "n_patch": sum(1 for s in steps if s.get("tool_name") == "apply_patch"),
            }
        per_run[run] = rows

    ids = sorted(set().union(*(set(rows) for rows in per_run.values())))

    print("== 逐实例首刀轮号（None = 该跑从未 apply_patch）==")
    header = f"{'instance_id':<28}" + "".join(f"{run:>26}" for run in RUNS)
    print(header)
    print(f"{'':<28}" + "".join(f"{'首刀/首py/步数':>22}" for _ in RUNS))
    for instance_id in ids:
        line = f"{instance_id:<28}"
        for run in RUNS:
            row = per_run[run].get(instance_id)
            if row is None:
                line += f"{'—':>26}"
            else:
                line += f"{row['first_patch']!s:>8}{row['first_python']!s:>8}{row['steps']:>8}  "
        print(line)

    print()
    for run in RUNS:
        rows = per_run[run]
        b_first = sorted(r["first_patch"] for r in rows.values() if r["first_patch"] is not None)
        a_ids = [i for i, r in rows.items() if r["first_patch"] is None]
        print(f"== {run} ==")
        print(f"  B 组（动过手）{len(b_first)} 条 / A 组（从未动手）{len(a_ids)} 条")
        if b_first:
            print(f"  B 组首刀轮号：min={b_first[0]} 中位={statistics.median(b_first)} max={b_first[-1]}")
            print(f"  分布={b_first}")
            for cut in (10, 12, 15, 18, 20, 25):
                n = sum(1 for x in b_first if x <= cut)
                print(f"  首刀 ≤{cut:>2} 轮的 B 组实例：{n}/{len(b_first)} ({n / len(b_first):.0%})")
        print(f"  A 组名单：{a_ids}")
        print()

    print("== 首刀之后还用了多少轮（steps - first_patch）：定 Implement+Verify 长度用 ==")
    for run in RUNS:
        tail = sorted(r["steps"] - r["first_patch"] for r in per_run[run].values() if r["first_patch"] is not None)
        print(f"  {run}: min={tail[0]} 中位={statistics.median(tail)} max={tail[-1]}  分布={tail}")
    print()

    both = [i for i in ids if all(per_run[run].get(i, {}).get("first_patch") is not None for run in RUNS)]
    print(f"== 两跑都动手的 {len(both)} 条：首刀轮号跑间差（㊾ 跑间方差）==")
    deltas = []
    for instance_id in both:
        vals = [per_run[run][instance_id]["first_patch"] for run in RUNS]
        delta = abs(vals[0] - vals[1])
        deltas.append(delta)
        print(f"  {instance_id:<28} {vals[0]:>3} vs {vals[1]:>3}   差 {delta}")
    if deltas:
        print(f"  差值：中位={statistics.median(deltas)} max={max(deltas)}")


if __name__ == "__main__":
    main()
