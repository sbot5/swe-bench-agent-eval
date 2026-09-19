"""单条实例逐轮的缓存读数：这一轮命中了多少、上一轮的 prompt 有多长。2026-09-19。

判读：会话若是纯追加（append-only），第 k 轮的 hit 应当约等于第 k-1 轮的 prompt（按缓存块取整）；
明显小于它 = 前缀在中途被改写了（或缓存还没建好）。
用法：PYTHONPATH=. .venv/bin/python scripts/p2_rerun_turns.py <run-id> <instance_id>
"""
import json
import pathlib
import sys

run, iid = sys.argv[1], sys.argv[2]
d = json.loads(pathlib.Path(f"results/inference/{run}/{iid}.traj.json").read_text())
turns = {}
tools = {}
for st in d["steps"]:
    turns.setdefault(st["index"], st)
    tools.setdefault(st["index"], []).append(st.get("tool") or st.get("tool_name") or "?")
print("StepRecord 键:", sorted(d["steps"][0]))
print(f"{'轮':>4}{'prompt':>9}{'hit':>9}{'miss':>8}{'上轮prompt':>11}{'hit/上轮':>9}  工具")
prev = None
for k in sorted(turns):
    st = turns[k]
    p, h, m = st["prompt_tokens"], st.get("cache_hit_tokens"), st.get("cache_miss_tokens")
    ratio = f"{h / prev:.0%}" if (prev and h is not None) else "-"
    print(f"{k:>4}{p:>9,}{h!s:>9}{m!s:>8}{prev or 0:>11,}{ratio:>9}  {','.join(tools[k])}")
    prev = p
