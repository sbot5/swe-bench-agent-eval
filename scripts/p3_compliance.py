"""P3：新 prompt 到底有没有被**遵守**（与「有没有用」是两个问题）。

动手数只答「有没有用」。如果动手数没动，还要能分清两种情况：
  (a) 模型照做了「两次复现不了就直接改」，但改不对 —— 那病不在 prompt
  (b) 模型根本没照做，还在无限复现 —— 那 prompt 改得不够硬
分不清就会把 (b) 误读成「prompt 不是病因」。

三个读数：
  1. run_python 连跑次数 —— 新 prompt 说两次不成就走，真照做的话长连跑应该消失
  2. thought 非空轮数与内容 —— 新 prompt 要求 "say in one line why"，说了就是收到了
  3. 首次 apply_patch 轮号 —— 照做的话第一刀应该提前

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p3_compliance.py [run-id ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INFER = REPO / "results" / "inference"

GROUP_A = [
    "django__django-10554",
    "django__django-11138",
    "pylint-dev__pylint-4551",
    "pylint-dev__pylint-8898",
    "sphinx-doc__sphinx-11510",
    "sphinx-doc__sphinx-8638",
    "sympy__sympy-17630",
    "sympy__sympy-18211",
]
RUNS = ["s5-mine", "p2-mine", "p2-rerun", "p3-r1", "p3-r2"]


def longest_run_of(steps: list[dict], tool: str) -> int:
    """按模型轮号（step['index']）算 tool 连续出现的最长轮数，一轮多次只记一轮。"""
    rounds = sorted({s["index"] for s in steps if s["tool_name"] == tool})
    if not rounds:
        return 0
    best = cur = 1
    for prev, now in zip(rounds, rounds[1:], strict=False):
        cur = cur + 1 if now == prev + 1 else 1
        best = max(best, cur)
    return best


def main(argv: list[str]) -> int:
    runs = argv[1:] or RUNS
    print(f"{'run':<10}{'实例':<16}{'py次':<6}{'py最长连轮':<12}{'思考轮':<8}{'首刀轮':<8}")
    for run in runs:
        for iid in GROUP_A:
            path = INFER / run / f"{iid}.traj.json"
            if not path.exists():
                continue
            steps = json.loads(path.read_text(encoding="utf-8"))["steps"]
            py = [s for s in steps if s["tool_name"] == "run_python"]
            edits = [s["index"] for s in steps if s["tool_name"] == "apply_patch"]
            thoughts = [s for s in steps if (s.get("thought") or "").strip()]
            print(f"{run:<10}{iid.split('__')[-1]:<16}{len(py):<6}{longest_run_of(steps, 'run_python'):<12}"
                  f"{len(thoughts):<8}{str(min(edits)) if edits else '-':<8}")
        print()

    print("=== 新 prompt 下非空 thought 的原文（前 200 字符）===")
    for run in [r for r in runs if r.startswith("p3")]:
        for iid in GROUP_A:
            path = INFER / run / f"{iid}.traj.json"
            if not path.exists():
                continue
            steps = json.loads(path.read_text(encoding="utf-8"))["steps"]
            seen: set[int] = set()
            for s in steps:
                text = (s.get("thought") or "").strip()
                if not text or s["index"] in seen:
                    continue
                seen.add(s["index"])
                print(f"\n[{run} {iid.split('__')[-1]} 轮{s['index']} →{s['tool_name']}] {text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
