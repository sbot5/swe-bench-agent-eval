"""P4 §3.5 合规性 + §3.2 反向指标 + §五 缓存读数（$0，只读已在库轨迹）。

口径一律不新造：
  - 段边界与段工具表 **从 agent/staged.py 直读**（见 scripts/p4_read.py 开头那条已纠正）
  - ARCH 词面沿用 scripts/areason_markers.py 的 MARKERS["ARCH"]
  - ARCH 行为沿用 scripts/switch_point.py 的判定（p2_groupa.classify + PR_PAT）

两处**补量**（㊿ 第三次：判据锁定挡得住改阈值，挡不住判据本身漏了量）：
  补量一 按轮算的考古率跨段不可比 —— Collect 段有两条探测通道（search_code 的 PR 词面 +
         run_python 的 classify），Implement 段只剩 run_python，**Verify 段两条都没有**
         （工具表里就没这两个工具）。所以补「只在能被探测到的轮里」的考古率。
  补量二 判据只锁了「动手数」，没锁「在哪动手」—— 补首刀轮号相对段边界的位置。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. python3 scripts/p4_analysis.py
"""

from __future__ import annotations

import collections
import json
import pathlib

from areason_markers import COMPILED
from areason_read import CONTROLS, GROUP_A, load
from p2_groupa import classify
from switch_point import PR_PAT, code_of

from agent.staged import COLLECT_END, IMPLEMENT_END, STAGE_TOOLS, stage_of

REPO = pathlib.Path(__file__).resolve().parent.parent
INFER = REPO / "results" / "inference"
RUNS = ("p4-r1", "p4-r2")
STAGES = ("COLLECT", "IMPLEMENT", "VERIFY")
ARCH_WORD = COMPILED["ARCH"]


def rounds_of(steps: list[dict]) -> dict[int, list[dict]]:
    by: dict[int, list[dict]] = collections.defaultdict(list)
    for s in steps:
        by[s["index"]].append(s)
    return dict(by)


def _sc_arch(s: dict) -> bool:
    q = json.dumps(s.get("tool_args") or {}, ensure_ascii=False)
    return any(p.search(q) for p in PR_PAT)


def arch_behaviour(rnd: list[dict]) -> bool:
    """switch_point.act 的 ARCH 判定，**去掉 FIX 短路** ——
    否则 Implement/Verify 段一动手就被记成 FIX，跨段率不可比。"""
    for s in rnd:
        if s["tool_name"] == "run_python" and classify(code_of(s)) == "ARCH":
            return True
        if s["tool_name"] == "search_code" and _sc_arch(s):
            return True
    return False


def arch_word(rnd: list[dict]) -> bool:
    return any(any(p.search(s.get("reasoning_content") or "") for p in ARCH_WORD)
               for s in rnd if s.get("reasoning_content"))


def results_of(run: str) -> dict:
    return json.loads((REPO / "logs" / "evaluation" / run / "results.json").read_text())


def sec_tools() -> None:
    print("=" * 96)
    print("A. 段工具表 —— agent/staged.py 直读")
    print("-" * 96)
    for stage in STAGES:
        print(f"  {stage:<10} {list(STAGE_TOOLS[stage])}")
    print("  ⚠️ 探测通道的结构性事实（C 节要用）：")
    print(f"     search_code 可用段：{[s for s in STAGES if 'search_code' in STAGE_TOOLS[s]]}")
    print(f"     run_python  可用段：{[s for s in STAGES if 'run_python' in STAGE_TOOLS[s]]}")


def sec_compliance() -> None:
    print("=" * 96)
    print("C. §3.5 合规性：Implement 段考古率 vs Collect 段（三把尺子）")
    print("-" * 96)
    for label, names in (("A 组", GROUP_A), ("对照", CONTROLS)):
        for run in RUNS:
            agg = {s: collections.Counter() for s in STAGES}
            det = {s: collections.Counter() for s in STAGES}
            for iid in names:
                steps = load(run, iid)
                if steps is None:
                    continue
                for idx, rnd in rounds_of(steps).items():
                    st = stage_of(idx)
                    agg[st]["n"] += 1
                    agg[st]["beh"] += arch_behaviour(rnd)
                    agg[st]["word"] += arch_word(rnd)
                    agg[st]["reas"] += any(s.get("reasoning_content") for s in rnd)
                    rp = [s for s in rnd if s["tool_name"] == "run_python"]
                    sc = [s for s in rnd if s["tool_name"] == "search_code"]
                    det[st]["rp"] += bool(rp)
                    det[st]["sc"] += bool(sc)
                    if rp or sc:
                        det[st]["n"] += 1
                        det[st]["arch"] += (any(classify(code_of(s)) == "ARCH" for s in rp)
                                            or any(_sc_arch(s) for s in sc))
            print(f"  [{label} · {run}]")
            print(f"    {'段':<10} {'轮数':>5} {'行为层':>12} {'可探测轮内':>13} {'词面层':>12} {'有reasoning':>12}")
            for s in STAGES:
                a, d = agg[s], det[s]
                n = a["n"] or 1
                dn = f"{d['arch']}/{d['n']} ({d['arch'] / d['n']:.1%})" if d["n"] else "0/0 (n/a)"
                print(f"    {s:<10} {a['n']:>5} "
                      f"{a['beh']:>4} ({a['beh'] / n:>5.1%}) {dn:>13} "
                      f"{a['word']:>4} ({a['word'] / n:>5.1%}) "
                      f"{a['reas']:>5} ({a['reas'] / n:>5.1%})")


def sec_first_edit() -> None:
    print("=" * 96)
    print(f"B. 首刀轮号相对段边界（Collect 结束 {COLLECT_END} / Implement 结束 {IMPLEMENT_END}）")
    print(f"   Verify 段相对 Implement 段摘掉的工具："
          f"{sorted(set(STAGE_TOOLS['IMPLEMENT']) - set(STAGE_TOOLS['VERIFY']))}")
    print("-" * 96)
    stages = collections.Counter()
    for run in RUNS:
        for iid in GROUP_A:
            steps = load(run, iid)
            if steps is None:
                continue
            ap = [s for s in steps if s["tool_name"] == "apply_patch"]
            if not ap:
                continue
            f = min(s["index"] for s in ap)
            stages[stage_of(f)] += 1
            print(f"  {run}  {iid.split('__')[-1]:<14} 首刀 {f:>3} ({stage_of(f)})"
                  f"  距 Implement 开始 {f - COLLECT_END:+d}"
                  f"  距 Verify 开始 {f - IMPLEMENT_END:+d}"
                  f"  该跑末轮 {max(s['index'] for s in steps)}")
    print(f"  首刀落段分布：{dict(stages)}")


def sec_reverse() -> None:
    print("=" * 96)
    print("D. §3.2 反向指标：A 组每条 (patch>0, resolved) 四格")
    print("-" * 96)
    for run in RUNS:
        res = results_of(run)
        resolved = set(res["resolved_ids"])
        amb = set(res["ambiguous_failure_ids"])
        cell = collections.Counter()
        detail = []
        for iid in GROUP_A:
            path = INFER / run / f"{iid}.traj.json"
            if not path.exists():
                continue
            patch = json.loads(path.read_text()).get("model_patch") or ""
            cell[(bool(patch), iid in resolved)] += 1
            if patch and iid not in resolved:
                detail.append(f"{iid.split('__')[-1]}({len(patch)}ch"
                              + (",harness标amb" if iid in amb else "") + ")")
        print(f"  {run}: 有patch且resolved {cell[(True, True)]} · "
              f"有patch但没过 {cell[(True, False)]} · 空patch {cell[(False, False)]}")
        print(f"    有 patch 但没过的是：{' · '.join(detail) or '(无)'}")
    print("  基线三跑 A 组 0/24 动手 → 三个 patch 桶全为 0")
    print("  ⚠️ harness 的 ambiguous 标签在这两条上都不成立，见 EVAL-P4-staged.md §8.4")


def sec_cache() -> None:
    print("=" * 96)
    print("E. §五 C24 的第一个真跑缓存读数（㉖ 口径：按 step['index'] 去重）")
    print("-" * 96)
    print(f"{'run':<8} {'轮数':>5} {'None轮':>6} {'hit':>11} {'miss':>11} {'命中率':>8} {'峰值prompt':>11}")
    for run in RUNS:
        hit = miss = none = rounds = peak = 0
        for iid in GROUP_A + CONTROLS:
            steps = load(run, iid)
            if steps is None:
                continue
            seen: set[int] = set()
            for s in steps:
                if s["index"] in seen:
                    continue
                seen.add(s["index"])
                rounds += 1
                h, m = s.get("cache_hit_tokens"), s.get("cache_miss_tokens")
                if h is None or m is None:
                    none += 1
                    continue
                hit += h
                miss += m
                peak = max(peak, h + m)
        tot = hit + miss
        rate = f"{hit / tot:.1%}" if tot else "n/a"
        print(f"{run:<8} {rounds:>5} {none:>6} {hit:>11,} {miss:>11,} {rate:>8} {peak:>11,}")
    print("  对照锚点（不同跑不可比绝对值，只比率与峰值）：")
    print("    EVAL-P2-rerun 整跑直读命中率 58.8%（25 条）")
    print("    EVAL-cache-sim 模拟攒 5 条：未命中字符 −53.9%、峰值 27,985 → 34,178 token")


def main() -> int:
    sec_tools()
    sec_first_edit()
    sec_compliance()
    sec_reverse()
    sec_cache()
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
