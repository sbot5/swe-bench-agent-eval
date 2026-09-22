"""P4 分阶段跑的主表：每条一行 + §3.1 主判据（$0，只读已在库轨迹）。

⚠️ 段边界与段工具表**一律从 agent/staged.py 直读**。
   09-22 头一版探针把 `CUT = (12, 32, 40)` 和 `STAGE_TOOLS` 手抄了一份，于是它报的
   「工具表违规 0」只证明「落盘 == 那份手抄表」，不证明「落盘 == 真正发出去的表」——
   与 Codex 二审 ⒝「指纹盖不住真正发出去的东西」同型。本版改成直读，违规数仍为 0。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. python3 scripts/p4_read.py
"""

from __future__ import annotations

import json
import pathlib

from agent.staged import STAGE_TOOLS, stage_of

REPO = pathlib.Path(__file__).resolve().parent.parent
INFER = REPO / "results" / "inference"
RUNS = ("p4-r1", "p4-r2")
CONTROL = {"django__django-14631", "sphinx-doc__sphinx-9711"}


def results_of(run: str) -> dict:
    return json.loads((REPO / "logs" / "evaluation" / run / "results.json").read_text())


def main() -> int:
    grand = 0
    for run in RUNS:
        res = results_of(run)
        resolved = set(res["resolved_ids"])
        unresolved = set(res["unresolved_ids"])
        empty = set(res["empty_patch_ids"])
        amb = set(res["ambiguous_failure_ids"])

        print("=" * 100)
        print(f"{run}  resolved: {len(resolved)}  unresolved: {len(unresolved)}  "
              f"empty: {len(empty)}  ambiguous: {sorted(amb)}")
        print("-" * 100)
        print(f"{'instance':<32} {'组':<3} {'轮':>4} {'apply':>6} {'C/I/V':<10} "
              f"{'首刀轮':>6} {'ok':>4} {'patch':>7} {'评测':<11} 工具表违规")

        for path in sorted(INFER.joinpath(run).glob("*.traj.json")):
            t = json.loads(path.read_text())
            iid = t["instance_id"]
            steps = t["steps"]
            grp = "对照" if iid in CONTROL else "A"

            ap = [s for s in steps if s["tool_name"] == "apply_patch"]
            by = {"COLLECT": 0, "IMPLEMENT": 0, "VERIFY": 0}
            for s in ap:
                by[stage_of(s["index"])] += 1
            first = min((s["index"] for s in ap), default=None)
            ok = sum(1 for s in ap if s["status"] == "ok")

            bad = sum(1 for s in steps
                      if list(s.get("tools_declared") or []) != list(STAGE_TOOLS[stage_of(s["index"])]))

            if iid in resolved:
                verdict = "RESOLVED"
            elif iid in empty:
                verdict = "empty"
            elif iid in unresolved:
                verdict = "unresolved"
            else:
                verdict = "?"
            if iid in amb:
                verdict += "*amb"

            rounds = max((s["index"] for s in steps), default=0)
            civ = f"{by['COLLECT']}/{by['IMPLEMENT']}/{by['VERIFY']}"
            print(f"{iid:<32} {grp:<3} {rounds:>4} {len(ap):>6} {civ:<10} "
                  f"{first!s:>6} {ok:>4} {len(t.get('model_patch') or ''):>7} {verdict:<11} {bad}")

        hit = sum(1 for p in sorted(INFER.joinpath(run).glob("*.traj.json"))
                  if json.loads(p.read_text())["instance_id"] not in CONTROL
                  and any(s["tool_name"] == "apply_patch" for s in json.loads(p.read_text())["steps"]))
        grand += hit

    print("=" * 100)
    print("§3.1 主判据（A 组 8 条 × 2 跑 = 16 个实例-跑组合，apply_patch>0 的个数）")
    for run in RUNS:
        hit = sum(1 for p in sorted(INFER.joinpath(run).glob("*.traj.json"))
                  if json.loads(p.read_text())["instance_id"] not in CONTROL
                  and any(s["tool_name"] == "apply_patch" for s in json.loads(p.read_text())["steps"]))
        print(f"  {run}: {hit}/8")
    print(f"  合计: {grand}/16   （阈值 >=5/16 且两跑各 >=2；基线三跑 0/24、P3 2/16）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
