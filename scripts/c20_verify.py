"""C20 的复现脚本（$0，不发请求、不起容器）：

① 加了缓存三列之后，gold 回放产出的 patch 与 P2 那次**逐字节**是否仍然相同
   —— 相同就说明 25/25 resolved 不必重跑评测即成立
② 新三列是否真的落进了 traj，以及假模型下取到的值是不是 None（负对照：没读到写 None，不写 0）

先跑回放再跑本脚本：

    PYTHONPATH=. .venv/bin/python tests/smoke_gold_replay.py --run-id c20-gold-replay --instances subset_ids.txt
    .venv/bin/python scripts/c20_verify.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "results" / "inference"
NEW, OLD = ROOT / "c20-gold-replay", ROOT / "p2-gold-replay"

COLUMNS = ("cache_hit_tokens", "cache_miss_tokens", "reasoning_tokens")


def patches(preds_path: Path) -> dict[str, str]:
    preds = json.loads(preds_path.read_text())
    rows = preds.values() if isinstance(preds, dict) else preds
    return {row["instance_id"]: row["model_patch"] for row in rows}


def main() -> int:
    new, old = patches(NEW / "preds.json"), patches(OLD / "preds.json")
    print(f"① 逐字节比对 preds.json：新 {len(new)} 条 / 旧 {len(old)} 条")
    print(f"   instance_id 集合相同: {set(new) == set(old)}")
    differing = [i for i in new if i in old and new[i] != old[i]]
    print(f"   patch 不同的条数: {len(differing)}  {differing if differing else '→ 全部逐字节相同'}")

    trajectories = sorted(NEW.glob("*.traj.json"))
    print(f"\n② traj 落盘检查（{len(trajectories)} 个文件）")
    first = json.loads(trajectories[0].read_text())["steps"][0]
    for column in COLUMNS:
        print(f"   {column:20s} 在 steps 的字段里: {column in first}")

    seen: dict[str, set] = {column: set() for column in COLUMNS}
    steps = 0
    for path in trajectories:
        for step in json.loads(path.read_text())["steps"]:
            steps += 1
            for column in COLUMNS:
                seen[column].add(step.get(column, "<MISSING>"))
    print(f"   全 {steps} 步取到的值: { {k: sorted(v, key=str) for k, v in seen.items()} }")
    print("   （gold 回放的假模型不产 usage，所以全 None —— 这正是负对照）")
    return 0 if not differing else 1


if __name__ == "__main__":
    raise SystemExit(main())
