"""P2 原样重跑的逐条读数：轮数、token、㉖ 三列、返回模型名。2026-09-19。

⚠️ 一轮多个 tool_call 会落多条 StepRecord 且共享同一轮的 token，按 step['index'] 去重（同 p2_tokens.py）。
㉖ 三列口径（决定 C20）：None = 供应商没给，0 = 真的没命中。None 单独计数，**绝不当 0 加**。
仪器自检：DeepSeek 的 hit + miss 应当等于 prompt_tokens，对不上的轮单独计数。
⚠️ calls − 轮 = 没有 tool_call 的调用：它不落 StepRecord（loop.py 在内层 for 里 append），token 不在 traj 里，
   所以这里的 token 合计**略少于真实消耗**（与 p2_tokens.py 同口径，两跑可比）。

用法：PYTHONPATH=. .venv/bin/python scripts/p2_rerun_check.py <run-id>
"""
import collections
import json
import pathlib
import sys

run = sys.argv[1]
files = sorted(pathlib.Path(f"results/inference/{run}").glob("*.traj.json"))
if not files:
    sys.exit(f"results/inference/{run} 下没有 traj")

print("traj 顶层键:", sorted(k for k in json.loads(files[0].read_text()) if k not in ("messages", "steps")))
print(f"{'instance':<34}{'calls':>6}{'轮':>5}{'输入tok':>11}{'输出tok':>9}{'hit':>11}{'miss':>10}"
      f"{'推理':>8}{'命中率':>8}{'None轮':>7}{'和≠入':>6}{'patch字符':>9}  stop_reason")

tot = collections.Counter()
models = collections.Counter()
for tf in files:
    d = json.loads(tf.read_text())
    turns = {}
    for st in d.get("steps", []):
        turns.setdefault(st["index"], st)
        models[st.get("returned_model")] += 1
    c = collections.Counter()
    for st in turns.values():
        c["in"] += st["prompt_tokens"]
        c["out"] += st["completion_tokens"]
        hit, miss, rsn = st.get("cache_hit_tokens"), st.get("cache_miss_tokens"), st.get("reasoning_tokens")
        if hit is None or miss is None:
            c["none_turns"] += 1
        else:
            c["hit"] += hit
            c["miss"] += miss
            c["in_with_cache"] += st["prompt_tokens"]
            if hit + miss != st["prompt_tokens"]:
                c["sum_mismatch"] += 1
        if rsn is None:
            c["none_rsn"] += 1
        else:
            c["rsn"] += rsn
    c["turns"] = len(turns)
    rate = f"{c['hit'] / c['in_with_cache']:.0%}" if c["in_with_cache"] else "-"
    print(f"{d['instance_id']:<34}{d.get('api_calls')!s:>6}{c['turns']:>5}{c['in']:>11,}{c['out']:>9,}"
          f"{c['hit']:>11,}{c['miss']:>10,}{c['rsn']:>8,}{rate:>8}{c['none_turns']:>7}{c['sum_mismatch']:>6}"
          f"{len(d.get('model_patch') or ''):>9,}  {d.get('stop_reason')}{' ERROR' if d.get('error') else ''}")
    tot.update(c)

print("-" * 120)
rate = f"{tot['hit'] / tot['in_with_cache']:.1%}" if tot["in_with_cache"] else "-"
print(f"{'合计 ' + str(len(files)) + ' 条':<34}{'':>6}{tot['turns']:>5}{tot['in']:>11,}{tot['out']:>9,}"
      f"{tot['hit']:>11,}{tot['miss']:>10,}{tot['rsn']:>8,}{rate:>8}{tot['none_turns']:>7}{tot['sum_mismatch']:>6}")
print(f"推理 token 为 None 的轮: {tot['none_rsn']} / {tot['turns']}")
print("returned_model（按 StepRecord 计）:", dict(models))
