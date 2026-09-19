"""P3 的判别量：A 组 8 条的「动手数」（apply_patch 调用数），与三跑基线并排。

为什么不用 resolved 总分：⑦⑨ 三次实证，同配置单次跑的 resolved 有 ±3 的方差，
单跑读不出一次修正的效果；而 A 组 8 条的 apply_patch 在 S5 / P2 / p2-rerun 三跑里
**24/24 次全是 0**，稳定到挪动一条就是信号（EVAL-P2-rerun.md:110-111）。

⚠️ 口径（S5 归因时踩过的⑩）：落盘的 steps 是**工具调用数**，api_calls 才是模型轮数。
本脚本数的是 steps 里 tool_name == apply_patch 的条数，即「动了几刀」，不是「几轮」。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p3_handson.py [run-id ...]
不给参数就按默认的三跑基线 + 本次两跑。
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
CONTROLS = ["django__django-14631", "sphinx-doc__sphinx-9711"]
BASELINES = ["s5-mine", "p2-mine", "p2-rerun"]
NEW_RUNS = ["p3-r1", "p3-r2"]


def short(instance_id: str) -> str:
    return instance_id.split("__")[-1]


def read_traj(run: str, instance_id: str) -> dict | None:
    path = INFER / run / f"{instance_id}.traj.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def stats(traj: dict) -> dict:
    steps = traj["steps"]
    calls: dict[str, int] = {}
    for step in steps:
        calls[step["tool_name"]] = calls.get(step["tool_name"], 0) + 1
    edits = [s for s in steps if s["tool_name"] == "apply_patch"]
    first_edit = min((s["index"] for s in edits), default=None)
    thoughts = sum(1 for s in steps if (s.get("thought") or "").strip())
    reasoning = sum(s.get("reasoning_tokens") or 0 for s in steps)
    return {
        "apply_patch": len(edits),
        "apply_patch_ok": sum(1 for s in edits if s["status"] == "ok"),
        "first_edit_step": first_edit,
        "run_python": calls.get("run_python", 0),
        "read_file": calls.get("read_file", 0),
        "search_code": calls.get("search_code", 0),
        "run_tests": calls.get("run_tests", 0),
        "api_calls": traj["api_calls"],
        "steps": len(steps),
        "patch_ch": len(traj.get("model_patch") or ""),
        "stop": traj["stop_reason"],
        "thoughts": thoughts,
        "reasoning_tokens": reasoning,
    }


def resolved_ids(run: str) -> set[str] | None:
    """评测产物里的白名单口径（⑩：绝不用 unresolved 做黑名单反推）。"""
    # ⚠️ resolved_instances 是**计数**（int），resolved_ids 才是名单 —— 别把两者搞混（⑩ 的邻居）。
    # 也别碰 total_instances：它是整个 Verified 500 条，不是这一跑的分母（CLAUDE.md 的「分母陷阱」）。
    path = REPO / "results" / "evaluation" / run / "results.json"
    if not path.exists():
        return None
    return set(json.loads(path.read_text(encoding="utf-8"))["resolved_ids"])


def report(runs: list[str]) -> None:
    for run in runs:
        rows = {i: read_traj(run, i) for i in GROUP_A + CONTROLS}
        present = {i: t for i, t in rows.items() if t is not None}
        if not present:
            print(f"\n### {run}: 没有 traj，跳过")
            continue
        res = resolved_ids(run)
        print(f"\n### {run}  （{len(present)}/{len(rows)} 条有 traj"
              + (f"，评测白名单 {len(res)} 条 resolved）" if res is not None else "，未找到评测产物）"))
        print(f"{'instance':<22}{'组':<5}{'动手':<6}{'首刀':<6}{'py':<5}{'read':<6}{'srch':<6}"
              f"{'test':<6}{'轮':<5}{'patch':<8}{'stop':<14}{'思考轮':<7}{'reason_tok':<11}res")
        a_edits = a_hands = 0
        for i in GROUP_A + CONTROLS:
            traj = rows[i]
            if traj is None:
                print(f"{short(i):<22}{'A' if i in GROUP_A else '对照':<5}(缺)")
                continue
            s = stats(traj)
            group = "A" if i in GROUP_A else "对照"
            if i in GROUP_A:
                a_edits += s["apply_patch"]
                a_hands += 1 if s["apply_patch"] else 0
            mark = "?" if res is None else ("RESOLVED" if i in res else "-")
            print(f"{short(i):<22}{group:<5}{s['apply_patch']:<6}"
                  f"{str(s['first_edit_step']) if s['first_edit_step'] is not None else '-':<6}"
                  f"{s['run_python']:<5}{s['read_file']:<6}{s['search_code']:<6}{s['run_tests']:<6}"
                  f"{s['api_calls']:<5}{s['patch_ch']:<8}{s['stop']:<14}"
                  f"{s['thoughts']:<7}{s['reasoning_tokens']:<11}{mark}")
        n_a = sum(1 for i in GROUP_A if rows[i] is not None)
        print(f"  → A 组 {n_a} 条：动手 {a_hands} 条 / apply_patch 共 {a_edits} 次")


def main(argv: list[str]) -> int:
    runs = argv[1:] or BASELINES + NEW_RUNS
    report(runs)
    print("\n判据：A 组的「动手 n 条」。基线 s5-mine / p2-mine / p2-rerun 应各为 0 条 / 0 次（24/24）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
