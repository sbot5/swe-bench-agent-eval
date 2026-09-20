"""待办② 的收尾核对：逐轮对比 `classify()` 新旧判定（$0，只读已在库轨迹）。

改 `classify()` 会动两份已发布文档（EVAL-switch-point.md / EVAL-P2-groupA.md）的读数。
「不静默改」要求把**所有**判定变化的轮列全，而不是只报我注意到的那几条 ——
所以本脚本从 git 取旧版 `p2_groupa.py`，与工作区版本逐轮对拍，并同时报 T 的新旧差。

旧版来源：`git show <ref>:scripts/p2_groupa.py`，默认 ref = 改动前的 HEAD（用 --ref 指定）。

跑法：python3 scripts/classify_diff.py --ref b999dc4 p2-mine p2-rerun a-reason-r1 a-reason-r2
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import pathlib
import subprocess
import tempfile

from areason_read import load
from p2_groupa import classify as classify_new
from switch_point import code_of, find_t, instances_all, script_exit


def load_old(ref: str):
    """把 <ref> 版本的 p2_groupa.py 取出来单独 import，拿它的 classify。"""
    src = subprocess.run(["git", "show", f"{ref}:scripts/p2_groupa.py"],
                         capture_output=True, text=True, check=True).stdout
    tmp = pathlib.Path(tempfile.mkdtemp()) / "p2_groupa_old.py"
    tmp.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("p2_groupa_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.classify


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--ref", default="HEAD", help="旧版 p2_groupa.py 的 git ref（默认 HEAD）")
    ap.add_argument("--dump", action="store_true", help="附变化轮的 code 原文（㊽：落点逐条读原文判）")
    ap.add_argument("--cap", type=int, default=250)
    a = ap.parse_args()

    old = load_old(a.ref)
    moved = collections.Counter()
    n_round = n_changed = 0
    t_changed = []

    for run in a.runs:
        rows = []
        for iid in instances_all(run):
            steps = load(run, iid)
            if steps is None:
                continue
            for s in steps:
                if s.get("tool_name") != "run_python":
                    continue
                n_round += 1
                o, n = old(code_of(s)), classify_new(code_of(s))
                if o != n:
                    n_changed += 1
                    moved[(o, n)] += 1
                    rows.append((iid, s["index"], o, n, script_exit(s), code_of(s)))
            t_old, t_new = find_t(steps, cls=old), find_t(steps)
            if t_old != t_new:
                t_changed.append((run, iid, t_old, t_new))

        print(f"\n=== {run} —— 判定变化 {len(rows)} 轮 ===")
        for iid, idx, o, n, ex, code in rows:
            print(f"   {iid:<34} 轮 {idx:>3}  {o:<12} → {n:<12} exit={ex}")
            if a.dump:
                cut = f"   …（共 {len(code)} 字符，截断）" if len(code) > a.cap else ""
                print(f"{cut}\n{code[:a.cap]}\n")

    print(f"\n{'=' * 90}\n总览（ref={a.ref}）\n{'=' * 90}")
    print(f"   run_python 轮合计 {n_round}，判定变化 {n_changed} 轮（{n_changed / n_round * 100:.1f}%）")
    for (o, n), c in sorted(moved.items(), key=lambda kv: -kv[1]):
        print(f"   {o:<12} → {n:<12} {c:>4}")
    print(f"\n   T 发生变化的实例 {len(t_changed)} 条：")
    for run, iid, t_old, t_new in t_changed:
        print(f"   {run:<14}{iid:<34} T {t_old!s:>5} → {t_new!s:<5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
