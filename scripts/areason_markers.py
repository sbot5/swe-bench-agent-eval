"""在 §1.3 选中的轮里扫词面标记（$0）——**只用于导航，不是判读**。

判据 §1.4 要求每条轨迹判一个主类、且每条附原文引用。词面标记帮我定位该读哪几轮，
**落点仍由读原文决定**。这里绝不能把计数直接当结论：
  - 标记是白名单，措辞换一种就漏（T10 那一课：黑白名单方向反了就出假读数）
  - 所以**必须打印「一个标记都没命中的轮」**，漏掉的东西要能看见（否则就是 ⑩ 那种静默误判）

跑法：PYTHONPATH=. .venv/bin/python scripts/areason_markers.py a-reason-r1 a-reason-r2
"""

from __future__ import annotations

import argparse
import re

from areason_read import CONTROLS, GROUP_A, instances, load, pick, turns

MARKERS: dict[str, list[str]] = {
    # 找上游的标准答案（H2 的典型词面）
    "ARCH": [r"upstream", r"\bI recall\b", r"my memory", r"from memory", r"the gold\b",
             r"actual fix", r"official fix", r"real fix", r"ticket #", r"\bPR #", r"\bcommit [0-9a-f]{6}"],
    # 自称复现成功
    "REPRO_OK": [r"I (?:have )?reproduced", r"found the reproduction", r"reproduction (?:works|succeeded)",
                 r"confirms? the (?:bug|issue|behaviou?r)", r"confirmed the (?:bug|issue|behaviou?r)"],
    # 自称复现不了
    "REPRO_NO": [r"(?:not|n't|cannot|can't|couldn't|unable to|failed to) reproduce",
                 r"different approach to reproduce", r"reproduction (?:failed|isn't|is not)"],
    # 已经想好改哪里
    "FIXLOC": [r"[Nn]ow the fix", r"the fix (?:is|would be|should be)", r"I'?ll implement",
               r"I should (?:change|modify|patch)", r"decide on the implementation"],
}
COMPILED = {k: [re.compile(p) for p in v] for k, v in MARKERS.items()}


def hits(text: str) -> list[str]:
    return [k for k, pats in COMPILED.items() if any(p.search(text) for p in pats)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()

    for run in a.runs:
        print(f"\n=============== {run} ===============")
        agg: dict[str, int] = {k: 0 for k in MARKERS}
        bare_total = sel_total = 0
        for iid in instances(run):
            if iid not in GROUP_A + CONTROLS:
                continue
            steps = load(run, iid)
            if steps is None:
                continue
            tmap, picked = turns(steps), pick(steps)
            per: dict[str, list[int]] = {k: [] for k in MARKERS}
            bare: list[int] = []
            for i in sorted(picked):
                h = hits(tmap[i]["reasoning"] or "")
                for k in h:
                    per[k].append(i)
                if not h:
                    bare.append(i)
                sel_total += 1
            for k in MARKERS:
                if per[k]:
                    agg[k] += len(per[k])
            bare_total += len(bare)
            tag = "" if iid in GROUP_A else " [对照]"
            body = "  ".join(f"{k}{per[k]}" for k in MARKERS if per[k]) or "(无标记)"
            print(f"{iid.split('__')[-1]:<14}{tag}\n    {body}\n    无标记轮 {bare}")
        print(f"--- 选中轮合计 {sel_total}，各标记命中轮次数 {agg}，一个都没命中 {bare_total} 轮")
    print("\n⚠️ 以上是词面导航，不是落点。落点按 §1.4 读原文判，每条附引用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
