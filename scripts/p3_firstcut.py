"""P3：那两条动手的实例，第一刀之前发生了什么？

这问题决定结论怎么读：
  - 「复现成功了才动手」→ 与新加的**放弃条款**无关，走的还是老路（第 3 条原来的路）
  - 「放弃复现直接动手」→ 放弃条款真生效了
两者都会让动手数 +1，混着读就会把运气当成效果。

顺带打印同一实例在基线跑里的序列做对比（它在那里从未动手）。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p3_firstcut.py
"""

from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
INFER = REPO / "results" / "inference"

# (run, instance)：P3 里动手的两条，各配一个基线跑做对比
CASES = [
    ("p3-r1", "sphinx-doc__sphinx-8638", "p2-mine"),
    ("p3-r2", "sympy__sympy-18211", "p2-rerun"),
]


def seq(run: str, iid: str) -> list[dict]:
    return json.loads((INFER / run / f"{iid}.traj.json").read_text(encoding="utf-8"))["steps"]


def show(run: str, iid: str, lo: int, hi: int) -> None:
    print(f"\n--- {run} / {iid.split('__')[-1]}  轮 {lo}~{hi} ---")
    for s in seq(run, iid):
        if not lo <= s["index"] <= hi:
            continue
        flag = "" if s["status"] == "ok" else f"  [{s['status']}/{s.get('failure_category')}]"
        summary = (s.get("summary") or "").replace("\n", " ")[:110]
        thought = (s.get("thought") or "").strip().replace("\n", " ")[:90]
        print(f"  轮{s['index']:<3}{s['tool_name']:<13}{summary}{flag}")
        if thought:
            print(f"        thought: {thought}")


def main() -> int:
    for run, iid, base in CASES:
        steps = seq(run, iid)
        first = min(s["index"] for s in steps if s["tool_name"] == "apply_patch")
        pys = [s for s in steps if s["tool_name"] == "run_python"]
        bad = [s for s in pys if s["status"] != "ok"]
        print(f"\n{'=' * 78}\n{run} / {iid.split('__')[-1]}：第一刀在轮 {first}")
        print(f"  run_python 共 {len(pys)} 次（工具层非 ok {len(bad)} 次）")
        # ⚠️ 结论「第一刀之前复现都跑通了」靠的是**脚本层 exit code**，不是 status —— 逐次打印，不许概括
        for s in pys:
            m = re.search(r"exit(?:ed with)? code (\d+)", s.get("summary") or "")
            where = "刀前" if s["index"] < first else "刀后"
            print(f"    轮{s['index']:<3}{where}  exit={m.group(1) if m else '?'}")
        show(run, iid, max(1, first - 5), first + 1)

        base_steps = seq(base, iid)
        base_py = [s for s in base_steps if s["tool_name"] == "run_python"]
        print(f"\n  [基线 {base} 同一条] run_python {len(base_py)} 次，轮号 {[s['index'] for s in base_py]}，"
              f"apply_patch {sum(1 for s in base_steps if s['tool_name'] == 'apply_patch')} 次")
        show(base, iid, 35, 40)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
