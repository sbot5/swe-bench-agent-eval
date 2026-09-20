"""用 ㉖ 三列直读数 × 官方分时单价闭合本跑成本（$0）——㉞ 的第三次独立验证。

单价【原文 https://api-docs.deepseek.com/zh-cn/quick_start/pricing，2026-09-19 抓取】
deepseek-flash，元/百万 token：命中 空闲 0.02 / 高峰 0.04 · 未命中 空闲 1 / 高峰 2 · 输出 空闲 4 / 高峰 8。
高峰 = 北京时间周一至周五 9:00-12:00、14:00-18:00 → **本跑是周日，全天空闲价**。

⚠️ 必须按 step["index"] 去重：一轮多工具会落多条 StepRecord，token 数会重复计（㉖ 的口径）。
⚠️ traj 的 token 只含有 tool_call 的轮，略少于真实消耗（同 p2_rerun_pricing.py 的已知偏差）。

跑法：PYTHONPATH=.:scripts .venv/bin/python scripts/areason_cost.py a-reason-r1 a-reason-r2
"""

from __future__ import annotations

import argparse

from areason_read import instances, load

HIT, MISS, OUT = 0.02, 1.0, 4.0  # 元/百万，空闲价


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--balance-delta", type=float, default=None, help="余额差（元），用于对账")
    a = ap.parse_args()

    grand = [0, 0, 0, 0, 0]  # hit, miss, out, 轮, None 轮
    for run in a.runs:
        tot = [0, 0, 0, 0, 0]
        for iid in instances(run):
            steps = load(run, iid)
            if steps is None:
                continue
            seen: set[int] = set()
            for s in steps:
                if s["index"] in seen:
                    continue
                seen.add(s["index"])
                # 输出 token 硬取键：键名写错时要当场 KeyError，不许 .get() 静默变 0。
                # 第一版正是 .get("output_tokens") or 0，字段真名是 completion_tokens，
                # 于是输出成本整块丢失、预测偏低 —— 与 cost=$0.0000 同型的假读数（已纠正，不静默改）。
                o = s["completion_tokens"]
                h, m = s.get("cache_hit_tokens"), s.get("cache_miss_tokens")
                if h is None or m is None:
                    tot[4] += 1
                    continue
                tot[0] += h
                tot[1] += m
                tot[2] += o
                tot[3] += 1
        cost = (tot[0] * HIT + tot[1] * MISS + tot[2] * OUT) / 1e6
        rate = tot[0] / (tot[0] + tot[1]) if (tot[0] + tot[1]) else 0
        print(f"{run}: 轮 {tot[3]}（三列为 None 的 {tot[4]} 轮）  命中 {tot[0]:,}  未命中 {tot[1]:,}  "
              f"输出 {tot[2]:,}  命中率 {rate:.1%}  空闲价预测 ¥{cost:.2f}")
        for i in range(5):
            grand[i] += tot[i]

    total = (grand[0] * HIT + grand[1] * MISS + grand[2] * OUT) / 1e6
    rate = grand[0] / (grand[0] + grand[1]) if (grand[0] + grand[1]) else 0
    print(f"\n合计：轮 {grand[3]}，命中率 {rate:.1%}，**空闲价预测 ¥{total:.2f}**")
    if a.balance_delta:
        print(f"实测余额差 ¥{a.balance_delta:.2f} → 预测/实际 = {total / a.balance_delta:.3f}")
        print("（预测偏低是已知偏差：traj 只记有 tool_call 的轮，且不含冒烟）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
