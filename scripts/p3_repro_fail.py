"""P3 的前提核查：A 组的「复现」到底失不失败？

新加的放弃条款（"If two attempts do not reproduce it…"）只在**复现失败**时才有机会触发。
如果 run_python 根本不失败，这条款就永远是死代码 —— 那么「A 组被第 3 条卡住」这个假设
即便成立，卡的机制也不是我以为的那个，改法自然不对症。

⚠️ 两个层次别混（㉘ 同型）：
  - step["status"]    = **工具层**：工具本身执行成功与否
  - summary 里的 exit code = **脚本层**：模型写的那段 Python 返回了什么
「复现失败」是脚本层的事。只看 status 会得出「零失败」的假读数。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p3_repro_fail.py
"""

from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
INFER = REPO / "results" / "inference"
EXIT_RE = re.compile(r"exit(?:ed with)? code (\d+)")

GROUP_A = [
    "django__django-10554", "django__django-11138", "pylint-dev__pylint-4551",
    "pylint-dev__pylint-8898", "sphinx-doc__sphinx-11510", "sphinx-doc__sphinx-8638",
    "sympy__sympy-17630", "sympy__sympy-18211",
]
RUNS = ["p2-mine", "p2-rerun", "p3-r1", "p3-r2"]  # s5-mine 没有 run_python 这个工具


def exits(steps: list[dict]) -> list[tuple[int, str]]:
    """按调用顺序返回 (轮号, exit code)；解析不出记 '?'。"""
    out = []
    for s in steps:
        if s["tool_name"] != "run_python":
            continue
        m = EXIT_RE.search(s.get("summary") or "")
        out.append((s["index"], m.group(1) if m else "?"))
    return out


def consecutive_fails(seq: list[tuple[int, str]]) -> int:
    """**相邻两次 run_python 调用**都失败的次数 —— 放弃条款说的「two attempts」就是这个。
    注意口径：两次调用之间夹着别的工具不算断，因为模型是在「连着试复现」。"""
    return sum(1 for a, b in zip(seq, seq[1:], strict=False) if a[1] not in ("0", "?") and b[1] not in ("0", "?"))


def main() -> int:
    print(f"{'run':<10}{'实例':<16}{'py次':<6}{'工具层非ok':<12}{'脚本层exit≠0':<14}{'相邻两次都败':<14}")
    totals: dict[str, list[int]] = {r: [0, 0, 0, 0] for r in RUNS}
    for run in RUNS:
        for iid in GROUP_A:
            path = INFER / run / f"{iid}.traj.json"
            if not path.exists():
                continue
            steps = json.loads(path.read_text(encoding="utf-8"))["steps"]
            pys = [s for s in steps if s["tool_name"] == "run_python"]
            tool_bad = sum(1 for s in pys if s["status"] != "ok")
            seq = exits(steps)
            script_bad = sum(1 for _, c in seq if c not in ("0", "?"))
            pair_bad = consecutive_fails(seq)
            print(f"{run:<10}{iid.split('__')[-1]:<16}{len(pys):<6}{tool_bad:<12}{script_bad:<14}{pair_bad:<14}")
            for i, v in enumerate([len(pys), tool_bad, script_bad, pair_bad]):
                totals[run][i] += v
        t = totals[run]
        rate = f"{t[2] / t[0]:.1%}" if t[0] else "-"
        print(f"{'  小计':<10}{'':<16}{t[0]:<6}{t[1]:<12}{t[2]:<14}{t[3]:<14}脚本层失败率 {rate}\n")

    all_py = sum(t[0] for t in totals.values())
    all_bad = sum(t[2] for t in totals.values())
    all_pair = sum(t[3] for t in totals.values())
    print(f"A 组四跑合计：run_python {all_py} 次，脚本层 exit≠0 {all_bad} 次（{all_bad / all_py:.1%}）")
    print(f"**相邻两次调用都失败：{all_pair} 次** —— 放弃条款说的「two attempts」正是这个条件。")
    print("\n=== P3 两跑里，出现过相邻两败的实例（条款本该触发的现场）===")
    for run in ["p3-r1", "p3-r2"]:
        for iid in GROUP_A:
            path = INFER / run / f"{iid}.traj.json"
            if not path.exists():
                continue
            steps = json.loads(path.read_text(encoding="utf-8"))["steps"]
            seq = exits(steps)
            if not consecutive_fails(seq):
                continue
            edits = [s["index"] for s in steps if s["tool_name"] == "apply_patch"]
            print(f"  {run} {iid.split('__')[-1]:<16} exit 序列 {[f'{i}:{c}' for i, c in seq]}"
                  f"  → 第一刀 {min(edits) if edits else '从未'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
