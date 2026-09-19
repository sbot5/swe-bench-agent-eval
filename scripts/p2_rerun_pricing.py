"""用官方分时单价闭合四跑的成本：重跑有 ㉖ 直读数 → 预测成本对余额差；另外三跑没有 → 由余额差反解命中率。2026-09-19。

单价【原文 https://api-docs.deepseek.com/zh-cn/quick_start/pricing ，2026-09-19 抓取】deepseek-flash，元 / 百万 token：
  输入（缓存命中）  空闲 0.02 · 高峰 0.04
  输入（缓存未命中）空闲 1    · 高峰 2
  输出              空闲 4    · 高峰 8
  注 (3)「空闲时段价格为高峰时段价格的一半。高峰时段为北京时间周一至周五 9:00 - 12:00、14:00 - 18:00」
时钟：WSL 与 Windows 都是 AEST（+1000），北京时间 = 本地 − 2 小时（2026-09-19 实测 `date`）。
⚠️ 该页不写这套分时价从哪天起生效 —— 09-17 / 09-18 是否同价【未知】，下面的一致性是对它的旁证，不是证明。
⚠️ traj 的 token 只含有 tool_call 的轮（见 p2_rerun_check.py 头注释），略少于真实消耗；表里给 api_calls/轮 的放大系数作敏感性。

用法：PYTHONPATH=. .venv/bin/python scripts/p2_rerun_pricing.py
"""
import json
import pathlib

PRICE = {"peak": (0.04, 2.0, 8.0), "offpeak": (0.02, 1.0, 4.0)}  # (hit, miss, out) 元/百万

# (跑次, 包含的 run 目录, 余额差 ¥, 本地开始时间, 北京时间, 时段, 余额差出处)
RUNS = [
    ("S4", ["s4-mine"], 2.24, "09-17 周四 13:34", "11:34", "peak", "EVAL-P2.md §5.3"),
    ("S5", ["s5-mine"], 5.27, "09-17 周四 14:36", "12:36", "offpeak", "EVAL-P2.md §5.3"),
    ("P2", ["p2-mine", "p2-smoke"], 11.15 - 0.01, "09-18 周五 16:16", "14:16", "peak", "EVAL-P2.md §5.1（减去 4 次探针的 ¥0.01）"),
    ("重跑", ["p2-rerun", "p2-rerun-smoke"], 54.13 - 48.22, "09-19 周六 12:55", "10:55", "offpeak", "本跑 ~/p2_rerun_balance.log"),
]


def tokens(run_dirs):
    t = dict(inp=0, out=0, hit=0, miss=0, turns=0, calls=0, has_cache=True)
    for r in run_dirs:
        for tf in pathlib.Path(f"results/inference/{r}").glob("*.traj.json"):
            d = json.loads(tf.read_text())
            turns = {}
            for st in d["steps"]:
                turns.setdefault(st["index"], st)
            for st in turns.values():
                t["inp"] += st["prompt_tokens"]
                t["out"] += st["completion_tokens"]
                if st.get("cache_hit_tokens") is None:
                    t["has_cache"] = False
                else:
                    t["hit"] += st["cache_hit_tokens"]
                    t["miss"] += st["cache_miss_tokens"]
            t["turns"] += len(turns)
            t["calls"] += d.get("api_calls") or 0
    return t


print(f"{'跑次':<6}{'时段':<8}{'北京':>6}{'输入M':>8}{'输出M':>7}{'余额差':>8}{'元/M入':>8}{'反解命中率':>10}{'×calls/轮':>11}{'直读命中率':>10}")
for name, dirs, cost, local, bj, tier, src in RUNS:
    t = tokens(dirs)
    p_hit, p_miss, p_out = PRICE[tier]
    i, o = t["inp"] / 1e6, t["out"] / 1e6
    h = (i * p_miss + o * p_out - cost) / (i * (p_miss - p_hit))
    k = t["calls"] / t["turns"]  # 没落 StepRecord 的调用按平均轮补上，看反解值挪多少
    hk = (k * i * p_miss + k * o * p_out - cost) / (k * i * (p_miss - p_hit))
    direct = f"{t['hit'] / (t['hit'] + t['miss']):.1%}" if t["has_cache"] else "（无仪器）"
    print(f"{name:<6}{'高峰' if tier == 'peak' else '空闲':<8}{bj:>6}{i:>8.3f}{o:>7.3f}{cost:>8.2f}{cost / i:>8.3f}{h:>10.1%}{hk:>11.1%}{direct:>10}")
    if t["has_cache"]:
        pred = t["hit"] / 1e6 * p_hit + t["miss"] / 1e6 * p_miss + o * p_out
        print(f"       ↳ 直读数 × 空闲单价 = 命中 ¥{t['hit'] / 1e6 * p_hit:.3f} + 未命中 ¥{t['miss'] / 1e6 * p_miss:.3f}"
              f" + 输出 ¥{o * p_out:.3f} = ¥{pred:.2f}；余额差 ¥{cost:.2f}；预测/实际 = {pred / cost:.3f}")
        print(f"       ↳ 若按高峰价 = ¥{pred * 2:.2f}（空闲价恰为高峰一半）")
    print(f"       [{local} 本地 · 余额差出处 {src}]")
