#!/usr/bin/env python3
"""S6 决定性实验：--max-steps 80 之下，首次 apply_patch 落在第几轮。

判别量与 scripts/s5_badcase2.py 的 A **同一定义** —— `steps` 里第一条
`tool_name == "apply_patch"` 的 `index`。`index` 是模型轮号（一轮发多个工具调用时重复），
所以它和「落在 41-80 之间」这个判据是同一把尺；`len(steps)` 是工具调用数，不是轮数。
换定义就与 S5 的数字不可比，这个文件存在的唯一理由就是锁住定义。

token 按轮去重（每轮一次 API 调用，取该 index 的第一条 step），用来算真实成本的分母。

用法：python3 scripts/s6_firstpatch.py [run-id ...]   默认 s6-maxsteps80
"""
import json
import sys
from pathlib import Path

ROOT = Path.home() / "swe-bench-eval/results/inference"


def first_apply_patch(steps):
    """S5 判别量 A 的原定义：首次 apply_patch 的轮号；从未调过返回 None。"""
    for step in steps:
        if step["tool_name"] == "apply_patch":
            return step["index"]
    return None


def per_round(steps):
    """每轮只留第一条 step —— 同一轮的多个工具调用共享同一次 API 调用的 token 计数。"""
    rounds = {}
    for step in steps:
        rounds.setdefault(step["index"], step)
    return list(rounds.values())


total_pt = total_ct = 0

for run_id in sys.argv[1:] or ["s6-maxsteps80"]:
    print(f"== {run_id} ==")
    for path in sorted((ROOT / run_id).glob("*.traj.json")):
        d = json.load(open(path, encoding="utf-8"))
        steps = d["steps"]
        fp = first_apply_patch(steps)
        calls = per_round(steps)
        pt = sum(s["prompt_tokens"] for s in calls)
        ct = sum(s["completion_tokens"] for s in calls)
        total_pt += pt
        total_ct += ct
        print(f"  {d['instance_id']}")
        print(f"    首次 apply_patch = {fp if fp else '—— 从未'}"
              f"   apply_patch 次数 = {sum(1 for s in steps if s['tool_name'] == 'apply_patch')}")
        print(f"    轮数 api_calls = {d['api_calls']}   工具调用 steps = {len(steps)}"
              f"   stop = {d['stop_reason']}   patch = {len(d['model_patch'])} 字符")
        print(f"    prompt_tok = {pt}   completion_tok = {ct}"
              f"   returned_model = {sorted({s['returned_model'] for s in steps})}")
        tools = {}
        for s in steps:
            tools[s["tool_name"]] = tools.get(s["tool_name"], 0) + 1
        print(f"    工具分布 = {dict(sorted(tools.items(), key=lambda kv: -kv[1]))}")

print(f"\n合计 token = {total_pt + total_ct}"
      f"（prompt {total_pt} + completion {total_ct}）")
print(f"按 S5 反推的 0.5226 元/1M【推算】= ¥{(total_pt + total_ct) / 1e6 * 0.5226:.3f}"
      f"   —— 真实成本仍以余额差为准，程序打印的 cost=$0 是假的")
