"""C21 的复现脚本（$0，不发请求、不起容器）：

① 加了 reasoning_content 之后，gold 回放产出的 patch 与**三次**历史回放是否仍逐字节相同
   —— 相同就说明 25/25 resolved 不必重跑评测即成立
② 这一列是否真的落进了 traj，以及假模型下取到的是不是 None
   （负对照：没读到写 None，不写 ""，口径同 C20 的 0 vs None）

对照三次而不是一次：拆包那回（12a9dfa）已经确认 p2/p3/c20 三份 preds 互相逐字节相同，
所以任何一份出现差异都能立刻分辨是「本次改动引入的」还是「基线本来就漂了」。

先跑回放再跑本脚本：

    PYTHONPATH=. .venv/bin/python tests/smoke_gold_replay.py --run-id c21-gold-replay --instances subset_ids.txt
    .venv/bin/python scripts/c21_verify.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "results" / "inference"
NEW = ROOT / "c21-gold-replay"
BASELINES = ("c20-gold-replay", "p3-gold-replay", "p2-gold-replay")

COLUMN = "reasoning_content"
# C20 那三列一起验，确认本次改动没碰坏它们
OLD_COLUMNS = ("cache_hit_tokens", "cache_miss_tokens", "reasoning_tokens")


def patches(preds_path: Path) -> dict[str, str]:
    preds = json.loads(preds_path.read_text())
    rows = preds.values() if isinstance(preds, dict) else preds
    return {row["instance_id"]: row["model_patch"] for row in rows}


def main() -> int:
    new = patches(NEW / "preds.json")
    total_chars = sum(len(patch) for patch in new.values())
    print(f"① 逐字节比对 preds.json：本次 {len(new)} 条，合计 {total_chars} 字符")

    failed = []
    for name in BASELINES:
        path = ROOT / name / "preds.json"
        if not path.exists():
            print(f"   {name:20s} 缺文件，跳过（不要当成通过）")
            failed.append(name)
            continue
        old = patches(path)
        same_ids = set(new) == set(old)
        differing = [i for i in new if i in old and new[i] != old[i]]
        verdict = "全部逐字节相同" if same_ids and not differing else f"差异 {differing or '集合不同'}"
        print(f"   {name:20s} {len(old):>3} 条  id 集合相同={same_ids}  → {verdict}")
        if not same_ids or differing:
            failed.append(name)

    trajectories = sorted(NEW.glob("*.traj.json"))
    print(f"\n② traj 落盘检查（{len(trajectories)} 个文件）")
    first = json.loads(trajectories[0].read_text())["steps"][0]
    for column in (COLUMN, *OLD_COLUMNS):
        print(f"   {column:20s} 在 steps 的字段里: {column in first}")

    seen = set()
    old_seen: dict[str, set] = {c: set() for c in OLD_COLUMNS}
    steps = 0
    for path in trajectories:
        for step in json.loads(path.read_text())["steps"]:
            steps += 1
            seen.add(step.get(COLUMN, "<MISSING>"))
            for column in OLD_COLUMNS:
                old_seen[column].add(step.get(column, "<MISSING>"))

    print(f"   全 {steps} 步 {COLUMN} 取到的值: {sorted(seen, key=str)}")
    print(f"   C20 三列（不该被本次改动碰到）: { {k: sorted(v, key=str) for k, v in old_seen.items()} }")
    print("   （gold 回放的假模型不产 reasoning，所以全 None —— 这正是负对照："
          "没读到写 None，不写空串）")

    ok = not failed and seen == {None}
    print(f"\n结论：{'通过' if ok else '未通过'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
