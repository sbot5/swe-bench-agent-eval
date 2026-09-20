"""待办②：量 `p2_groupa.classify()` 的 REPRO 白名单漏检面（$0，只读已在库轨迹）。

背景（docs/EVAL-switch-point.md）：
  §4.4 抓到 1 例「纯内置语法、没有 import 的复现」被判成非 REPRO；
  §七第 2 条把影响面列为【未知】，并指出**不能只扫 UNCLASSIFIED** ——
  真正漏的是被 `BROWSE_PAT` 的 `open()` 之类**先命中**、根本进不了 UNCLASSIFIED 桶的那些。

判据（本探针只负责圈出候选，不判对错）：
  T = 首个「run_python + 脚本层 exit 0 + classify()==REPRO」的轮（switch_point.find_t）。
  → 只有**轮号 < 当前 T** 的漏判才会让 T 偏晚；**T 不存在**时全部轮都是候选。
  → exit 非 0 的轮不进候选（find_t 本来就要求 exit 0，漏不漏都不影响 T）。
  → exit 解析不出（'?'）的轮**单独计数**：find_t 同样会跳过它们，是第二个漏源。

本脚本**不改 classify**，只打印现场供逐条读原文判（㊽：词面只作导航，落点逐条读原文判）。

跑法：python3 scripts/classify_audit.py p2-mine p2-rerun
     python3 scripts/classify_audit.py --dump p2-mine p2-rerun    # 附 code 原文
"""

from __future__ import annotations

import argparse
import collections

from areason_read import load
from p2_groupa import classify
from switch_point import code_of, find_t, first_edit, instances_all, script_exit

CAP = 1500  # 单条 code 打印上限，超出显式标注


def rows(run: str) -> list[dict]:
    out = []
    for iid in instances_all(run):
        steps = load(run, iid)
        if steps is None:
            continue
        out.append({
            "iid": iid,
            "T": find_t(steps, strict=True),
            "T_loose": find_t(steps, strict=False),
            "first_edit": first_edit(steps),
            "rp": [s for s in steps if s.get("tool_name") == "run_python"],
        })
    return out


def candidates(r: dict) -> list[dict]:
    """可能影响 T 的轮：轮号 < 当前 T（T 不存在则全部）、非 REPRO、exit 为 0 或 '?'。"""
    out = []
    for s in r["rp"]:
        if r["T"] is not None and s["index"] >= r["T"]:
            continue
        kind, ex = classify(code_of(s)), script_exit(s)
        if kind == "REPRO" or ex not in ("0", "?"):
            continue
        out.append({"idx": s["index"], "kind": kind, "exit": ex, "code": code_of(s)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--dump", action="store_true", help="打印候选轮的 code 原文")
    ap.add_argument("--kind", nargs="*", help="只 dump 这些类别（ARCH / BROWSE / TRIVIAL / UNCLASSIFIED）")
    ap.add_argument("--cap", type=int, default=CAP, help=f"单条 code 打印上限（默认 {CAP}）")
    ap.add_argument("--quiet", action="store_true", help="只出 dump，不打表格与分布")
    a = ap.parse_args()

    grand = collections.Counter()
    for run in a.runs:
        rs = rows(run)
        n_cand = n_inst = 0
        if not a.quiet:
            print(f"\n{'=' * 100}\n{run}   n={len(rs)}\n{'=' * 100}")
            print(f"{'instance':<34}{'组':<4}{'T':>5}{'Tlo':>5}{'首刀':>6}{'rpy':>5}   候选轮 (轮号:类别/exit)")
        for r in rs:
            cand = candidates(r)
            n_cand += len(cand)
            n_inst += 1 if cand else 0
            for s in r["rp"]:
                grand[(classify(code_of(s)), script_exit(s))] += 1
            if a.quiet:
                continue
            brief = " ".join(f"{c['idx']}:{c['kind'][:5]}/{c['exit']}" for c in cand) or "-"
            print(f"{r['iid']:<34}{'A' if r['first_edit'] is None else 'B':<4}"
                  f"{r['T']!s:>5}{r['T_loose']!s:>5}{r['first_edit'] or '从未'!s:>6}"
                  f"{len(r['rp']):>5}   {brief}")

        no_t = [r["iid"] for r in rs if r["T"] is None]
        if not a.quiet:
            print(f"\n-- {run} 小结 --")
            print(f"   T 不存在的实例：{len(no_t)}/{len(rs)}  {no_t}")
            print(f"   候选轮合计 {n_cand} 条，涉及 {n_inst} 个实例")

        if a.dump:
            for r in rs:
                for c in candidates(r):
                    if a.kind and c["kind"] not in a.kind:
                        continue
                    code = c["code"]
                    cut = f"  …（共 {len(code)} 字符，截断）" if len(code) > a.cap else ""
                    print(f"\n-- [{run}] {r['iid']} 轮 {c['idx']}  "
                          f"判 {c['kind']} / exit {c['exit']}  (T={r['T']}){cut}")
                    print(code[:a.cap])

    if not a.quiet:
        print(f"\n{'=' * 100}\n全体 run_python 的 (classify, exit) 分布 —— 含 T 之后的轮，仅作背景\n{'=' * 100}")
        for (k, ex), n in sorted(grand.items(), key=lambda kv: -kv[1]):
            print(f"   {k:<14} exit={ex:<3} {n:>5}")
        print(f"   {'合计':<14}{'':<8}{sum(grand.values()):>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
