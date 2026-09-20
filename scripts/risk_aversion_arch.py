"""判读阶段的对照（$0）：ARCH 词表在「全量 766 轮」上的读数。

**不参与主判据。** 主判据（docs/EVAL-risk-aversion.md §1.5）只用选段 186 轮。
本脚本只回答必报项 2 的后一半：选段外 RISK 命中少，是不是因为选段外**什么都少**
（即选段规则本身就挑走了「话多的轮」）——只有拿同一批轮上的 ARCH 当标尺才答得了。

⚠️ ARCH 词表**原样 import** scripts/areason_markers.py，一个字不改：它是
   EVAL-A-reasoning.md 那 80 次的实现，改它就会动已发表的数字（待办② 的教训）。

跑法：PYTHONPATH=. .venv/bin/python scripts/risk_aversion_arch.py a-reason-r1 a-reason-r2
"""

from __future__ import annotations

import argparse

from areason_markers import COMPILED as MK
from areason_read import CONTROLS, GROUP_A, instances, load, pick, turns

ARCH = MK["ARCH"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    grand = [0, 0, 0, 0]
    for run in a.runs:
        print(f"\n=============== {run} ===============")
        print(f"{'实例':<16}{'组':<4}{'选段轮':<7}{'选段ARCH':<10}{'全量轮':<7}{'全量ARCH':<10}选段外 ARCH 轮")
        tot = [0, 0, 0, 0]
        for iid in instances(run):
            if iid not in GROUP_A + CONTROLS:
                continue
            steps = load(run, iid)
            if steps is None:
                continue
            tmap, picked = turns(steps), pick(steps)
            full = [i for i in sorted(tmap) if any(p.search(tmap[i]["reasoning"] or "") for p in ARCH)]
            sel = [i for i in full if i in picked]
            outside = [i for i in full if i not in picked]
            grp = "A" if iid in GROUP_A else "B"
            print(f"{iid.split('__')[-1]:<16}{grp:<4}{len(picked):<7}{len(sel):<10}"
                  f"{len(tmap):<7}{len(full):<10}{outside}")
            for k, v in enumerate([len(picked), len(sel), len(tmap), len(full)]):
                tot[k] += v
        print(f"  小计：选段 {tot[0]} 轮中 ARCH {tot[1]} 轮（{tot[1] / tot[0]:.0%}）｜"
              f"全量 {tot[2]} 轮中 ARCH {tot[3]} 轮（{tot[3] / tot[2]:.0%}）")
        grand = [g + t for g, t in zip(grand, tot)]
    print(f"\n两跑合计：选段 {grand[0]} 轮 / ARCH {grand[1]} 轮（{grand[1] / grand[0]:.0%}）｜"
          f"全量 {grand[2]} 轮 / ARCH {grand[3]} 轮（{grand[3] / grand[2]:.0%}）")
    print("⚠️ 这是词面导航，不是落点；ARCH 的落点判读见 EVAL-A-reasoning.md §三。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
