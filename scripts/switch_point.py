"""判别量：复现成功之后切换到哪（$0，只读已在库轨迹）。

判据**锁定**于 docs/EVAL-switch-point.md §二，commit 172a4ef —— 本脚本只是它的实现，
不许在看到读数之后改落点类别或阈值。

两个已有口径各缺一半，本脚本把它们合成（§2.1）：
  p2_groupa.classify(code)  —— 这段 code 在干什么，但**不看跑成没跑成**
  summary 里的 exit code    —— 成败，但**不看代码在干什么**（会把 print(x.__version__) 算成复现）
⚠️ step["status"] 是**工具层**，不是脚本层（㉘ / P3 §五第 1 条，P3 第一版栽在这里）。

跑法：python3 scripts/switch_point.py p2-mine p2-rerun
     python3 scripts/switch_point.py --cross a-reason-r1 a-reason-r2   # §五 交叉验证用
"""

from __future__ import annotations

import argparse
import collections
import json
import re

from areason_read import CONTROLS, EXIT_RE, GROUP_A, INFER, load, turns
from p2_groupa import classify

# §2.2 的 ARCH 补充判定：search_code 查询里的上游 PR 号词面
PR_PAT = [re.compile(p) for p in (r"#\d{4,5}", r"pull/\d+", r"\.patch\b", r"\.diff\b")]
FIX_FULL = ("apply_patch", "run_tests")
FIX_NOEDIT = ("run_tests",)  # §2.6 反同义反复对照


def code_of(step: dict) -> str:
    return (step.get("tool_args") or {}).get("code", "") or ""


def script_exit(step: dict) -> str:
    """脚本层 exit code；解析不出记 '?'（沿用 p3_repro_fail.py:33-41）。"""
    m = EXIT_RE.search(step.get("summary") or "")
    return m.group(1) if m else "?"


def find_t(steps: list[dict], strict: bool = True) -> int | None:
    """T = 首次**成功**复现的轮号（§2.1）。strict=False 即 T_loose（去掉 classify 条件）。"""
    for s in steps:
        if s["tool_name"] != "run_python" or script_exit(s) != "0":
            continue
        if strict and classify(code_of(s)) != "REPRO":
            continue
        return s["index"]
    return None


def fold(steps: list[dict]) -> dict[int, list[dict]]:
    """按 step["index"] 折叠成轮，保留该轮全部 StepRecord（turns() 只留工具名，这里要 args/summary）。"""
    out: dict[int, list[dict]] = {}
    for s in steps:
        out.setdefault(s["index"], []).append(s)
    return out


def act(rnd: list[dict], fix_tools: tuple[str, ...]) -> str:
    """该轮落 FIX / ARCH / DIAG，优先级 FIX > ARCH > DIAG（§2.2，命中即止）。"""
    if any(s["tool_name"] in fix_tools for s in rnd):
        return "FIX"
    for s in rnd:
        if s["tool_name"] == "run_python" and classify(code_of(s)) == "ARCH":
            return "ARCH"
        if s["tool_name"] == "search_code":
            q = json.dumps(s.get("tool_args") or {}, ensure_ascii=False)
            if any(p.search(q) for p in PR_PAT):
                return "ARCH"
    return "DIAG"


def landing(steps: list[dict], k: int, strict: bool,
            fix_tools: tuple[str, ...]) -> tuple[str, int | None, list[str]]:
    """主量：T+1..T+k 窗口内**首个**决定性动作（§2.3）。"""
    t = find_t(steps, strict)
    if t is None:
        return "NO_T", None, []
    rnd = fold(steps)
    window = [i for i in sorted(rnd) if i > t][:k]
    seq = [act(rnd[i], fix_tools) for i in window]
    for a in seq:
        if a in ("FIX", "ARCH"):
            return f"{a}_FIRST", t, seq
    return "NEITHER", t, seq


def first_edit(steps: list[dict]) -> int | None:
    e = [s["index"] for s in steps if s["tool_name"] == "apply_patch"]
    return min(e) if e else None


def instances_all(run: str) -> list[str]:
    have = sorted(p.name[: -len(".traj.json")] for p in (INFER / run).glob("*.traj.json"))
    known = [i for i in GROUP_A + CONTROLS if i in have]
    return known + [i for i in have if i not in known]


def rows_for(run: str, k: int, strict: bool, fix_tools: tuple[str, ...]) -> list[dict]:
    out = []
    for iid in instances_all(run):
        steps = load(run, iid)
        if steps is None:
            continue
        land, t, seq = landing(steps, k, strict, fix_tools)
        fe = first_edit(steps)
        out.append({
            "iid": iid, "land": land, "T": t, "seq": seq, "first_edit": fe,
            "grp_actual": "A" if fe is None else "B",
            "grp_fixed": "A" if iid in GROUP_A else "B",
            "rounds": len(turns(steps)),
        })
    return out


def share(rows: list[dict], grp_key: str, grp: str) -> tuple[int, int, str]:
    """某组里 ARCH_FIRST 的条数 / T 存在的条数（NO_T 不进分母，§2.3）。"""
    sub = [r for r in rows if r[grp_key] == grp]
    denom = [r for r in sub if r["land"] != "NO_T"]
    arch = [r for r in denom if r["land"] == "ARCH_FIRST"]
    pct = f"{len(arch) / len(denom) * 100:.0f}%" if denom else "-"
    return len(arch), len(denom), pct


def report_main(runs: list[str], k: int, strict: bool) -> dict[str, list[dict]]:
    allrows = {}
    for run in runs:
        rows = rows_for(run, k, strict, FIX_FULL)
        allrows[run] = rows
        print(f"\n{'=' * 96}\n{run}   n={len(rows)}   K={k}   T={'严口径' if strict else 'T_loose'}\n{'=' * 96}")
        print(f"{'instance':<34}{'实算':<5}{'名单':<5}{'T':>4}{'首刀':>5}  {'落点':<12}{'窗口序列'}")
        for r in sorted(rows, key=lambda r: (r["grp_actual"], r["iid"])):
            print(f"{r['iid']:<34}{r['grp_actual']:<5}{r['grp_fixed']:<5}"
                  f"{r['T']!s:>4}{r['first_edit'] or '从未'!s:>5}  {r['land']:<12}{r['seq']}")

        for key, label in (("grp_actual", "实算组（apply_patch==0）"), ("grp_fixed", "固定名单组（GROUP_A 8 条）")):
            print(f"\n-- {label} --")
            for g in "AB":
                a, d, p = share(rows, key, g)
                sub = [r for r in rows if r[key] == g]
                no_t = sum(1 for r in sub if r["land"] == "NO_T")
                dist = collections.Counter(r["land"] for r in sub)
                print(f"   {g} 组 n={len(sub):2d}  ARCH_FIRST {a}/{d} = {p:<5} NO_T={no_t}  {dict(dist)}")
    return allrows


def gate(allrows: dict[str, list[dict]], k: int) -> None:
    """§2.5 过线三条 —— 由数据算出来打印，不许无条件打印结论（areason_read.py:134 的教训）。"""
    print(f"\n{'=' * 96}\n§2.5 过线条件（三条全满足才算判别量成立）\n{'=' * 96}")
    ok1 = ok2 = ok3 = True
    for run, rows in allrows.items():
        aa, ad, _ = share(rows, "grp_actual", "A")
        ba, bd, _ = share(rows, "grp_actual", "B")
        ap = aa / ad * 100 if ad else 0.0
        bp = ba / bd * 100 if bd else 0.0
        gap = ap - bp
        hit = gap >= 30
        ok1 &= hit
        print(f"  ①分离度 {run}: A {ap:.0f}% − B {bp:.0f}% = {gap:+.0f}pp  "
              f"(阈值 +30pp) → {'过' if hit else '不过'}")

    for run, rows in allrows.items():
        n = sum(1 for r in rows if r["grp_fixed"] == "A" and r["land"] == "ARCH_FIRST")
        hit = n >= 4
        ok2 &= hit
        print(f"  ②两跑同向 {run}: 固定名单 A 组 ARCH_FIRST {n}/8 (阈值 ≥4) → {'过' if hit else '不过'}")

    tot_lead = tot_fix = 0
    for run, rows in allrows.items():
        sub = [r for r in rows if r["grp_actual"] == "B" and r["land"] == "FIX_FIRST"]
        lead = [r for r in sub if r["first_edit"] is not None and r["T"] is not None
                and r["first_edit"] > r["T"]]
        tot_fix += len(sub)
        tot_lead += len(lead)
        print(f"  ③下游性 {run}: B 组 FIX_FIRST 中首刀轮号 > T 的 {len(lead)}/{len(sub)}")
    if tot_fix:
        r3 = tot_lead / tot_fix * 100
        ok3 = r3 >= 80
        print(f"     合计 {tot_lead}/{tot_fix} = {r3:.0f}% (阈值 ≥80%) → {'过' if ok3 else '不过'}")
    else:
        ok3 = False
        print("     B 组无 FIX_FIRST 实例 → 第 3 条无法判定，按不过记账")

    verdict = ok1 and ok2 and ok3
    print(f"\n  ⇒ 三条 {'全部满足 —— 判别量成立' if verdict else '未全部满足 —— 判别量不成立，按失败记账（§2.5 禁止改口径重算）'}")
    print(f"     ①{'过' if ok1 else '不过'} ②{'过' if ok2 else '不过'} ③{'过' if ok3 else '不过'}")


def report_extras(runs: list[str]) -> None:
    print(f"\n{'=' * 96}\n§2.6 反同义反复对照：FIX 只含 run_tests（把 apply_patch 剔出 FIX）\n{'=' * 96}")
    for run in runs:
        rows = rows_for(run, 5, True, FIX_NOEDIT)
        for g in "AB":
            a, d, p = share(rows, "grp_actual", g)
            dist = collections.Counter(r["land"] for r in rows if r["grp_actual"] == g)
            print(f"  {run} {g} 组: ARCH_FIRST {a}/{d} = {p:<5} {dict(dist)}")

    print(f"\n{'=' * 96}\n§2.7 阈值敏感性\n{'=' * 96}")
    for k in (3, 5, 10):
        for strict in (True, False):
            line = [f"  K={k:<3}{'严' if strict else '宽'}口径:"]
            for run in runs:
                rows = rows_for(run, k, strict, FIX_FULL)
                aa, ad, ap = share(rows, "grp_actual", "A")
                ba, bd, bp = share(rows, "grp_actual", "B")
                no_t = sum(1 for r in rows if r["land"] == "NO_T")
                line.append(f"{run} A {aa}/{ad}={ap} B {ba}/{bd}={bp} NO_T={no_t}")
            print("  ".join(line))

    print(f"\n{'=' * 96}\n§2.2 必报：白名单漏检面（A 组窗口内的 DIAG 轮）与 UNCLASSIFIED 全文\n{'=' * 96}")
    unc: list[tuple[str, str, int, str]] = []
    for run in runs:
        rows = rows_for(run, 5, True, FIX_FULL)
        diag = sum(s.count("DIAG") for s in (r["seq"] for r in rows if r["grp_actual"] == "A"))
        wtot = sum(len(r["seq"]) for r in rows if r["grp_actual"] == "A")
        print(f"  {run}: A 组窗口 {wtot} 轮，其中 DIAG {diag} 轮"
              f"（ARCH 白名单若漏，漏的会落在这里）")
        for iid in instances_all(run):
            steps = load(run, iid)
            for s in steps or []:
                if s["tool_name"] == "run_python" and classify(code_of(s)) == "UNCLASSIFIED":
                    unc.append((run, iid, s["index"], code_of(s)))
    print(f"\n  UNCLASSIFIED 共 {len(unc)} 次（不许静默归桶，⑩ 的教训）：")
    for run, iid, idx, code in unc:
        print(f"\n  --- {run} {iid} 轮 {idx} ---\n{code}")


def cross(runs: list[str]) -> None:
    """§五 交叉验证：在有 reasoning 的两跑上算本量，供与 H2 逐条落点比对。"""
    print(f"\n{'=' * 96}\n§五 交叉验证取数（a-reason 两跑，K=5 严口径）\n{'=' * 96}")
    for run in runs:
        rows = rows_for(run, 5, True, FIX_FULL)
        print(f"\n-- {run} --")
        print(f"{'instance':<34}{'组':<4}{'T':>4}{'首刀':>5}  {'落点':<12}{'窗口序列'}")
        for r in sorted(rows, key=lambda r: r["iid"]):
            tag = "A" if r["iid"] in GROUP_A else ("对照" if r["iid"] in CONTROLS else "外")
            print(f"{r['iid']:<34}{tag:<4}{r['T']!s:>4}{r['first_edit'] or '从未'!s:>5}  "
                  f"{r['land']:<12}{r['seq']}")
        arch = sorted(r["iid"] for r in rows if r["land"] == "ARCH_FIRST")
        print("  本量判 ARCH_FIRST 的实例集（与 EVAL-A-reasoning.md §1.5 的 H2 落点比对）：")
        for i in arch:
            print(f"    {i}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--cross", action="store_true", help="§五 交叉验证模式")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()

    if a.cross:
        cross(a.runs)
        return 0

    allrows = report_main(a.runs, a.k, strict=True)
    gate(allrows, a.k)
    report_extras(a.runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
