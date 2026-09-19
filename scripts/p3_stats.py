"""P3 的两个算账：①「动手 2/16 vs 基线 0/24」有多显著 ② 成本闭合（㉖ 三列 × 官方分时单价）。

单价与时钟口径照抄 scripts/p2_rerun_pricing.py（元/百万 token，北京时间 = 本地 − 2 小时）。
P3 两跑都在 **北京时间周六 19:03–19:13**，周末全天空闲价。

⚠️ 显著性这一段是给**自己**定「要不要再花钱跑」用的，不是拿去讲结论的 ——
n 这么小，不显著不等于没效果，显著也不等于有效果。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p3_stats.py
"""

from __future__ import annotations

import json
import pathlib
from math import comb

REPO = pathlib.Path(__file__).resolve().parent.parent
INFER = REPO / "results" / "inference"
PRICE_OFFPEAK = (0.02, 1.0, 4.0)  # (hit, miss, out) 元/百万

GROUP_A = [
    "django__django-10554", "django__django-11138", "pylint-dev__pylint-4551",
    "pylint-dev__pylint-8898", "sphinx-doc__sphinx-11510", "sphinx-doc__sphinx-8638",
    "sympy__sympy-17630", "sympy__sympy-18211",
]
BASELINE_RUNS = ["s5-mine", "p2-mine", "p2-rerun"]
P3_RUNS = ["p3-r1", "p3-r2"]


def edits(run: str, iid: str) -> int | None:
    path = INFER / run / f"{iid}.traj.json"
    if not path.exists():
        return None
    steps = json.loads(path.read_text(encoding="utf-8"))["steps"]
    return sum(1 for s in steps if s["tool_name"] == "apply_patch")


def fisher_upper(a: int, b: int, c: int, d: int) -> float:
    """2x2 表 [[a,b],[c,d]] 的单侧（上尾）Fisher 精确 p 值。"""
    n1, n2, k = a + b, c + d, a + c
    return sum(
        comb(n1, x) * comb(n2, k - x) / comb(n1 + n2, k)
        for x in range(a, min(n1, k) + 1)
    )


def tokens(run_dirs: list[str]) -> dict[str, int]:
    """㉖ 三列直读。⚠️ 取不到记 None 不记 0，所以这里只累加真有读数的轮。"""
    out = {"hit": 0, "miss": 0, "out": 0, "steps_with": 0, "steps_without": 0}
    for run in run_dirs:
        for path in (INFER / run).glob("*.traj.json"):
            seen: set[int] = set()
            for s in json.loads(path.read_text(encoding="utf-8"))["steps"]:
                if s["index"] in seen:  # 一轮多工具会重复落盘，按 index 去重（㉖ 口径）
                    continue
                seen.add(s["index"])
                if s.get("cache_hit_tokens") is None:
                    out["steps_without"] += 1
                    continue
                out["steps_with"] += 1
                out["hit"] += s["cache_hit_tokens"]
                out["miss"] += s["cache_miss_tokens"]
                out["out"] += s["completion_tokens"] or 0
    return out


def main() -> int:
    print("=== ① 判别量：A 组 8 条的动手数 ===")
    base_hands = [(r, i) for r in BASELINE_RUNS for i in GROUP_A if edits(r, i)]
    p3_hands = [(r, i) for r in P3_RUNS for i in GROUP_A if edits(r, i)]
    nb, np3 = len(BASELINE_RUNS) * len(GROUP_A), len(P3_RUNS) * len(GROUP_A)
    print(f"基线 {len(base_hands)}/{nb} 次动手（{BASELINE_RUNS}）")
    print(f"P3   {len(p3_hands)}/{np3} 次动手 → {[f'{r}:{i.split('__')[-1]}' for r, i in p3_hands]}")

    a, b = len(p3_hands), np3 - len(p3_hands)
    c, d = len(base_hands), nb - len(base_hands)
    print(f"\n2x2 [[P3 动手 {a}, 没动手 {b}], [基线 {c}, {d}]]")
    print(f"Fisher 单侧 p = {fisher_upper(a, b, c, d):.4f}  → {'显著' if fisher_upper(a,b,c,d) < 0.05 else '不显著（p > 0.05）'}")

    # 配对着看：同一条实例在基线三跑 vs P3 两跑，控制掉「实例难度」这个固定效应
    up = [i for i in GROUP_A
          if not any(edits(r, i) for r in BASELINE_RUNS) and any(edits(r, i) for r in P3_RUNS)]
    down = [i for i in GROUP_A
            if any(edits(r, i) for r in BASELINE_RUNS) and not any(edits(r, i) for r in P3_RUNS)]
    print(f"配对：8 条里向上 {len(up)} 条 {[i.split('__')[-1] for i in up]}，向下 {len(down)} 条")
    if up or down:
        n_pairs = len(up) + len(down)
        print(f"符号检验单侧 p = {sum(comb(n_pairs, x) for x in range(len(up), n_pairs + 1)) / 2 ** n_pairs:.4f}")

    print("\n=== ② 成本闭合：㉖ 直读数 × 空闲单价（北京周六 19:03–19:13）===")
    t = tokens(["p3-r1", "p3-r2", "p3-smoke"])
    p_hit, p_miss, p_out = PRICE_OFFPEAK
    pred = t["hit"] / 1e6 * p_hit + t["miss"] / 1e6 * p_miss + t["out"] / 1e6 * p_out
    total_in = t["hit"] + t["miss"]
    print(f"轮数 有读数 {t['steps_with']} / 无读数 {t['steps_without']}")
    print(f"输入 {total_in / 1e6:.2f}M（命中 {t['hit'] / 1e6:.2f}M = {t['hit'] / total_in:.1%}，未命中 {t['miss'] / 1e6:.2f}M）"
          f" 输出 {t['out'] / 1e6:.3f}M")
    print(f"预测成本 = 命中 ¥{t['hit'] / 1e6 * p_hit:.3f} + 未命中 ¥{t['miss'] / 1e6 * p_miss:.3f}"
          f" + 输出 ¥{t['out'] / 1e6 * p_out:.3f} = **¥{pred:.2f}**")
    print(f"（同样的量按高峰价 = ¥{pred * 2:.2f}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
