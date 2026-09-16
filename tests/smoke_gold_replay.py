"""端到端冒烟：用 gold patch 当假模型，把整条链跑一遍，$0。

    PYTHONPATH=. .venv/bin/python tests/smoke_gold_replay.py --run-id gold-replay --instances subset_ids.txt

跑完拿产出的 preds.json 走真评测（答案已知：S1 实测 gold 25/25 resolved）：

    .venv/bin/swebench eval verified -p results/inference/<run-id>/preds.json --run-id <run-id> -j 6

不是 25/25 就说明链上有 bug，而不是模型不行 —— 这正是它存在的理由。
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agent.loop import LoopConfig
from agent.run import REPO_ROOT_DIR, load_instances, run_instance
from tests.gold_replay import GoldReplayClient, parse_patch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="gold-replay")
    parser.add_argument("--instances", default="subset_ids.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    out_dir = REPO_ROOT_DIR / "results" / "inference" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    instances = load_instances(REPO_ROOT_DIR / args.instances, args.limit)
    # 每条实例的步数上限就是它的 hunk 数 + finish，没有模型在这里做判断
    config = LoopConfig(max_steps=200, cost_limit=float("inf"), wall_clock_limit=3600.0,
                        max_consecutive_tool_errors=200, max_file_edit_failures=200)

    print(f"replaying gold patches over {len(instances)} instances, workers={args.workers}", flush=True)
    started = time.time()
    rows: list[dict] = []
    preds: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_instance, instance,
                        client_factory=lambda patch=instance["patch"]: GoldReplayClient(parse_patch(patch)),
                        config=config, out_dir=out_dir): instance
            for instance in instances
        }
        for future in as_completed(futures):
            instance = futures[future]
            row = future.result()
            trajectory = json.loads((out_dir / f"{row['instance_id']}.traj.json").read_text(encoding="utf-8"))
            row["hunks"] = len(parse_patch(instance["patch"]))
            row["gold_patch_chars"] = len(instance["patch"])
            rows.append(row)
            preds[row["instance_id"]] = {
                "instance_id": row["instance_id"],
                "model_name_or_path": "gold-replay",
                "model_patch": trajectory["model_patch"],
            }
            flag = "ok " if row["tool_errors"] == 0 and row["patch_chars"] > 0 else "BAD"
            print(f"[{len(rows)}/{len(instances)}] {flag} {row['instance_id']} "
                  f"hunks={row['hunks']} edit_errors={row['tool_errors']} patch={row['patch_chars']}ch "
                  f"{row['wall_seconds']}s", flush=True)

    (out_dir / "preds.json").write_text(json.dumps(preds, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps({"run_id": args.run_id, "model": "gold-replay",
                    "elapsed_seconds": round(time.time() - started, 1),
                    "instances": sorted(rows, key=lambda item: item["instance_id"])},
                   indent=2, ensure_ascii=False),
        encoding="utf-8")

    clean = sum(1 for row in rows if row["tool_errors"] == 0 and row["patch_chars"] > 0)
    print(f"\n{clean}/{len(rows)} instances replayed with no failed edit; "
          f"{round(time.time() - started, 1)}s")
    print(f"preds: {out_dir / 'preds.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
