"""按 docs/EVAL-A-reasoning.md §1.3 从轨迹里抠 reasoning 片段（$0）。

取数范围是**跑前锁定**的，这个脚本只是它的实现，不许在跑完之后改选段规则：
  (a) 首次 run_python 拿到**脚本层** exit 0 的那一轮的**下一轮**
  (b) 末 5 轮
  (c) reasoning_content 命中 `reproduc` 词根的所有轮

⚠️ 两个层次别混（㉘ / P3 §五第 1 条）：
  step["status"]    = 工具层，工具本身跑没跑起来
  summary 里 exit code = 脚本层，模型写的那段 Python 返回了什么
「复现成功」是脚本层的事。解析沿用 scripts/p3_repro_fail.py:33-41。

⚠️ 一轮多工具会落多条 StepRecord，reasoning_content 在同一轮里重复出现 ——
必须按 step["index"] 去重（㉖ 的口径，CLAUDE.md 记过）。

跑法：
  PYTHONPATH=. .venv/bin/python scripts/areason_read.py --stats a-reason-r1 a-reason-r2
  PYTHONPATH=. .venv/bin/python scripts/areason_read.py --excerpt a-reason-r1
负对照（C21 之前的跑，三列与 reasoning 应全 None）：
  PYTHONPATH=. .venv/bin/python scripts/areason_read.py --stats p3-r1 p3-r2
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
INFER = REPO / "results" / "inference"
EXIT_RE = re.compile(r"exit(?:ed with)? code (\d+)")
REPRO_RE = re.compile(r"reproduc", re.IGNORECASE)
CAP = 3000  # 单轮引用上限，超出显式标注；判据 §1.4 要求判读附原文

GROUP_A = [
    "django__django-10554", "django__django-11138", "pylint-dev__pylint-4551",
    "pylint-dev__pylint-8898", "sphinx-doc__sphinx-11510", "sphinx-doc__sphinx-8638",
    "sympy__sympy-17630", "sympy__sympy-18211",
]
CONTROLS = ["django__django-14631", "sphinx-doc__sphinx-9711"]


def instances(run: str) -> list[str]:
    """名单 10 条在前，跑里多出来的（如冒烟那条）排在后面，一条都不漏看。"""
    have = sorted(p.name[: -len(".traj.json")] for p in (INFER / run).glob("*.traj.json"))
    known = [i for i in GROUP_A + CONTROLS if i in have]
    return known + [i for i in have if i not in known]


def load(run: str, iid: str) -> list[dict] | None:
    path = INFER / run / f"{iid}.traj.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["steps"]


def turns(steps: list[dict]) -> dict[int, dict]:
    """按轮号折叠：一轮一条记录，带该轮调用过的工具名。reasoning/thought 取该轮首条。"""
    out: dict[int, dict] = {}
    for s in steps:
        i = s["index"]
        if i not in out:
            out[i] = {
                "index": i,
                "reasoning": s.get("reasoning_content"),
                "reasoning_tokens": s.get("reasoning_tokens"),
                "thought": s.get("thought"),
                "tools": [],
            }
        out[i]["tools"].append(s["tool_name"])
    return out


def py_exits(steps: list[dict]) -> list[tuple[int, str]]:
    """(轮号, 脚本层 exit code)，按调用顺序；解析不出记 '?'。"""
    return [
        (s["index"], m.group(1) if (m := EXIT_RE.search(s.get("summary") or "")) else "?")
        for s in steps if s["tool_name"] == "run_python"
    ]


def pick(steps: list[dict]) -> dict[int, list[str]]:
    """§1.3 的三段，返回 {轮号: [命中的段代号]}。"""
    tmap = turns(steps)
    picked: dict[int, list[str]] = {}
    order = sorted(tmap)

    # (a) 首次脚本层 exit 0 的下一轮
    first_ok = next((i for i, c in py_exits(steps) if c == "0"), None)
    if first_ok is not None:
        nxt = next((i for i in order if i > first_ok), None)
        if nxt is not None:
            picked.setdefault(nxt, []).append("a")

    # (b) 末 5 轮
    for i in order[-5:]:
        picked.setdefault(i, []).append("b")

    # (c) reasoning 里谈复现的所有轮
    for i in order:
        if REPRO_RE.search(tmap[i]["reasoning"] or ""):
            picked.setdefault(i, []).append("c")

    return picked


def stats(runs: list[str]) -> None:
    hdr = f"{'run':<14}{'实例':<16}{'轮':<5}{'有reasoning':<12}{'py次':<6}{'脚本exit0':<11}{'apply':<7}{'选段轮'}"
    print(hdr)
    print("-" * len(hdr))
    for run in runs:
        tot = [0, 0, 0, 0, 0]
        got = instances(run)
        for iid in got:
            steps = load(run, iid)
            if steps is None:
                continue
            tmap = turns(steps)
            has = sum(1 for t in tmap.values() if t["reasoning"])
            seq = py_exits(steps)
            ok0 = sum(1 for _, c in seq if c == "0")
            edits = [s["index"] for s in steps if s["tool_name"] == "apply_patch"]
            sel = sorted(pick(steps))
            tag = "" if iid in GROUP_A else ("  [对照]" if iid in CONTROLS else "  [名单外]")
            print(f"{run:<14}{iid.split('__')[-1]:<16}{len(tmap):<5}{has:<12}{len(seq):<6}"
                  f"{ok0:<11}{len(edits):<7}{sel}{tag}")
            for k, v in enumerate([len(tmap), has, len(seq), ok0, len(edits)]):
                tot[k] += v
        print(f"{'  小计':<14}{'':<16}{tot[0]:<5}{tot[1]:<12}{tot[2]:<6}{tot[3]:<11}{tot[4]:<7}")
        missing = [i for i in GROUP_A + CONTROLS if i not in got]
        print(f"  名单缺失：{[m.split('__')[-1] for m in missing] or '(无)'}\n")
    print("有reasoning=0 且这一跑在 C21 之后 → 落 H5，主问题作废（判据 §1.4）")


def excerpt(run: str) -> None:
    out = [f"# {run} —— reasoning 选段（脚本产物，选段规则锁定于 docs/EVAL-A-reasoning.md §1.3）\n"]
    for iid in instances(run):
        steps = load(run, iid)
        if steps is None:
            continue
        tmap, picked = turns(steps), pick(steps)
        edits = [s["index"] for s in steps if s["tool_name"] == "apply_patch"]
        seq = py_exits(steps)
        role = ("A 组" if iid in GROUP_A else
                "对照（B 组，只作定性参照，不进 §1.5 分母）" if iid in CONTROLS else "名单外")
        out.append(f"\n## {iid}  [{role}]\n")
        out.append(f"- 轮数 {len(tmap)}，run_python {len(seq)} 次，脚本层 exit 序列 "
                   f"{[f'{i}:{c}' for i, c in seq]}")
        out.append(f"- apply_patch 轮号：{edits or '从未'}\n")
        for i in sorted(picked):
            t = tmap[i]
            r = t["reasoning"]
            body = "(reasoning_content = None —— 供应商没给 / 仪器不在)" if r is None else (
                "(reasoning_content = 空串)" if r == "" else
                (r[:CAP] + f"\n…[截断，原文 {len(r)} 字符]" if len(r) > CAP else r))
            out.append(f"### 轮 {i}  段{''.join(picked[i])}  工具={t['tools']}  "
                       f"reasoning_tokens={t['reasoning_tokens']}")
            out.append(f"thought = {t['thought']!r}\n")
            out.append("```\n" + body + "\n```\n")
    dest = INFER / run / "reasoning-excerpt.md"
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"写出 {dest}（{dest.stat().st_size} 字节）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--excerpt", action="store_true")
    a = ap.parse_args()
    if a.stats or not a.excerpt:
        stats(a.runs)
    if a.excerpt:
        for r in a.runs:
            excerpt(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
