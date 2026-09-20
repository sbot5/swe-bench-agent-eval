"""repair 闸的 N 怎么定（$0，只读已在库轨迹）。

判据**锁定**于 docs/EVAL-repair-gate-N.md §二，commit 9c1bda7 —— 本脚本只是它的实现，
不许在看到读数之后改阈值或分组。过线三条由数据算出来打印，不许无条件打印结论
（areason_read.py:134 的教训）。

闸的形状【原文 Monash 13-工业scaffold调研.md §五】：
  T 之后累计 N 轮仍无 apply_patch → 摘掉 search_code / list_files / run_python，
  保留 read_file / apply_patch / run_tests / git_diff，直到第一次 apply_patch。

跑法：python3 scripts/repair_gate_n.py p2-mine p2-rerun
     python3 scripts/repair_gate_n.py --cross a-reason-r1 a-reason-r2
"""

from __future__ import annotations

import argparse

from areason_read import GROUP_A, load
from switch_point import find_t, first_edit, instances_all

GATED = ("search_code", "list_files", "run_python")  # 闸摘掉的三个
CANDIDATE_N = (3, 5, 8, 10, 15, 20, 25, 30)          # §2.5
MAX_STEPS = 40                                        # --max-steps 上限，S6 已证不加大
PASS_A_MIN = 6                                        # §2.8 条件 1：A 组可触发 ≥ 6/8
PASS_B_MAX = 2                                        # §2.8 条件 2：B 组有效误伤 ≤ 2


def pct(xs: list[int], p: float) -> float:
    """线性插值分位数（小样本，不引 numpy）。"""
    s = sorted(xs)
    k = (len(s) - 1) * p
    f = int(k)
    return float(s[f]) if f == k else s[f] + (k - f) * (s[f + 1] - s[f])


def rows(run: str) -> list[dict]:
    out = []
    for iid in instances_all(run):
        steps = load(run, iid)
        if steps is None:
            continue
        t, fe = find_t(steps), first_edit(steps)
        out.append({
            "iid": iid, "steps": steps, "T": t, "fe": fe,
            "grp": "A" if fe is None else "B",
            # §2.3：只对 T 存在且 first_edit > T 的 B 组实例算 delta
            "delta": fe - t if (t is not None and fe is not None and fe > t) else None,
        })
    return out


def gated_calls(steps: list[dict], lo: int, hi: int) -> int:
    """[lo, hi) 轮里对被摘工具的调用次数（§2.6，窗口起点取 T+N 是保守口径，见文档 §3.3）。"""
    return sum(1 for s in steps
               if lo <= s["index"] < hi and s.get("tool_name") in GATED)


def report(run: str, rs: list[dict]) -> dict:
    b = [r for r in rs if r["grp"] == "B"]
    a = [r for r in rs if r["grp"] == "A"]
    ok = [r for r in b if r["delta"] is not None]
    no_t = [r for r in b if r["T"] is None]
    before = [r for r in b if r["T"] is not None and r["fe"] is not None and r["fe"] <= r["T"]]

    print(f"\n{'=' * 96}\n{run}   n={len(rs)}   A={len(a)}  B={len(b)}\n{'=' * 96}")
    print(f"{'B 组实例':<34}{'T':>5}{'首刀':>6}{'delta':>7}")
    for r in sorted(b, key=lambda r: (r["delta"] is None, r["delta"] or 0)):
        print(f"{r['iid']:<34}{r['T']!s:>5}{r['fe']!s:>6}{r['delta']!s:>7}")

    d = [r["delta"] for r in ok]
    print(f"\n-- delta = 首刀 − T 的分布（§2.3/§2.4，n={len(d)}）--")
    print(f"   中位 {pct(d, .5):.1f}   P75 {pct(d, .75):.1f}   P90 {pct(d, .9):.1f}   max {max(d)}")
    print(f"   N_safe = max(delta)+1 = {max(d) + 1}  （零误触发所需的 N）")
    print(f"   单列不进分母：T 不存在 {len(no_t)} 条 {[r['iid'] for r in no_t]}")
    print(f"                 首刀早于 T {len(before)} 条 {[r['iid'] for r in before]}")

    print(f"\n-- 误触发面（§2.5）与有效误伤（§2.6）--")
    print(f"{'N':>4}{'误触发':>8}{'误触发率':>10}{'有效误伤':>10}   被掐断的实例 (窗口内被摘工具调用数)")
    per_n = {}
    for n in CANDIDATE_N:
        hit = [r for r in ok if r["delta"] > n]
        harm = []
        for r in hit:
            c = gated_calls(r["steps"], r["T"] + n, r["fe"])
            if c > 0:
                harm.append((r["iid"], c))
        per_n[n] = {"hit": len(hit), "harm": len(harm)}
        brief = " ".join(f"{i.split('__')[-1]}({c})" for i, c in harm) or "-"
        print(f"{n:>4}{len(hit):>8}{len(hit) / len(ok) * 100:>9.0f}%{len(harm):>10}   {brief}")

    a_has_t = [r for r in a if r["T"] is not None]
    print(f"\n-- A 组可触发性（§2.7，A 组 n={len(a)}）--")
    print(f"   T 存在 {len(a_has_t)}/{len(a)} 条"
          f"{'' if len(a_has_t) == len(a) else '  T 不存在 = 闸结构性无效：' + str([r['iid'] for r in a if r['T'] is None])}")
    print(f"{'N':>4}{'T+N<=40 的条数':>16}   来不及触发的实例")
    for n in CANDIDATE_N:
        late = [r["iid"] for r in a_has_t if r["T"] + n > MAX_STEPS]
        per_n[n]["a_ok"] = len(a_has_t) - len(late)
        brief = " ".join(i.split("__")[-1] for i in late) or "-"
        print(f"{n:>4}{len(a_has_t) - len(late):>10}/{len(a):<5}   {brief}")
    return {"per_n": per_n, "n_a": len(a), "n_b_ok": len(ok)}


def gate(res: dict[str, dict]) -> None:
    """§2.8 过线三条 —— 全满足才算「N 可定」。"""
    print(f"\n{'=' * 96}\n§2.8 过线条件（三条全满足才算 N 可定）\n{'=' * 96}")
    feasible = {}
    for run, r in res.items():
        ok_n = [n for n, v in r["per_n"].items()
                if v["a_ok"] >= PASS_A_MIN and v["harm"] <= PASS_B_MAX]
        feasible[run] = set(ok_n)
        print(f"  {run}: 满足 ①A 可触发≥{PASS_A_MIN}/8 且 ②有效误伤≤{PASS_B_MAX} 的 N = "
              f"{sorted(ok_n) if ok_n else '空集'}")
        for n, v in r["per_n"].items():
            print(f"      N={n:<3} A 可触发 {v['a_ok']}/{r['n_a']}"
                  f"{' ✗' if v['a_ok'] < PASS_A_MIN else ' ✓'}"
                  f"   有效误伤 {v['harm']}/{r['n_b_ok']}"
                  f"{' ✗' if v['harm'] > PASS_B_MAX else ' ✓'}")
    inter = set.intersection(*feasible.values()) if feasible else set()
    print(f"\n  ③ 两跑可行 N 的交集 = {sorted(inter) if inter else '空集'}")
    print(f"  → 三条{'全满足，N 可定' if inter else '未全满足，**N 定不出来**'}"
          f"{'：N ∈ ' + str(sorted(inter)) if inter else '（不许放宽阈值凑数）'}")


def tvar(runs: list[str], n: int) -> None:
    """§四 补报（⚠️ **不在 §二 锁定判据内**，是算完 N 之后才发现必须报的，不得用来改 N）：

    ① T 自己在跑间摆多少 —— T 是闸的触发器，它不稳则 T+N 这个时点不可靠（㊶ 同型）。
    ② 闸触发后还剩几轮能动手 = MAX_STEPS − (T + N) —— §2.7 只查了 T+N ≤ 40，
       没查「触发后有没有作用空间」。
    """
    print(f"\n{'=' * 96}\n§四 补报（不在锁定判据内）：T 的跑间方差 + 触发后剩余轮数 @N={n}\n{'=' * 96}")
    print(f"{'A 组固定名单':<34}" + "".join(f"{r.replace('a-reason-', 'ar-'):>12}" for r in runs)
          + f"{'极差':>6}{'剩余轮数(40−T−N)':>20}")
    for iid in GROUP_A:
        ts = []
        for run in runs:
            steps = load(run, iid)
            ts.append(find_t(steps) if steps is not None else None)
        known = [t for t in ts if t is not None]
        rng = f"{max(known) - min(known)}" if len(known) >= 2 else "-"
        left = " ".join(f"{MAX_STEPS - t - n}" if t is not None else "-" for t in ts)
        print(f"{iid:<34}" + "".join(f"{t!s:>12}" for t in ts) + f"{rng:>6}{left:>20}")
    print(f"\n   「-」= 该跑 T 不存在（闸结构性无效）；剩余轮数 ≤0 = 触发了也没有作用空间")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--tvar", type=int, metavar="N",
                    help="只出 §四 补报：T 的跑间方差与该 N 下的触发后剩余轮数")
    a = ap.parse_args()
    if a.tvar is not None:
        tvar(a.runs, a.tvar)
        return 0
    res = {run: report(run, rows(run)) for run in a.runs}
    gate(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
