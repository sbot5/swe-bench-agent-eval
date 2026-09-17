"""mini baseline 跑 25 条的成本估算依据（S7 跑前估价，2026-09-17）。

为什么要这个脚本：
  - mini 的 `info.model_stats` 只有 `instance_cost` 和 `api_calls`，**没有 token 数**；
    而那个 instance_cost 是 S2（09-06）在中转站上按 litellm 价格表算的，模型也不是现在的
    `openai/deepseek-flash` —— 不能直接当 DeepSeek 官方端点的账。
  - 我方 scaffold 落盘的 `total_cost` 恒为 0（litellm 不认这个模型名），唯一可信成本是
    **余额差**：S5 的 25 条 = ¥5.27。
  - 所以估法只能是：用两边轨迹里**实际发出去的字符数**当代理量，
    从 S5 的余额差反推「¥ / 百万字符」，再乘 mini 的字符量。

口径（写死在这里，方便复核）：
  - 两边都是 append-only 会话、每轮重发全history → 每次模型调用的输入 = 该 assistant 消息之前的全部消息。
    "cum_in" = 对每次调用把当时的 history 字符数累加（这就是计费意义上的输入量）。
  - "out" = assistant 消息的 content + tool_calls 序列化后的字符数。
  - 字符不是 token。英文代码大致 3.5~4 字符/token，但**两边同尺度**，配对比值不受这个常数影响。
"""

import collections
import glob
import json
import os
import sys

REPO = os.path.expanduser("~/swe-bench-eval")


def clen(m):
    c = m.get("content")
    n = 0
    if isinstance(c, str):
        n += len(c)
    elif isinstance(c, list):
        n += sum(len(json.dumps(x, ensure_ascii=False)) for x in c)
    tc = m.get("tool_calls")
    if tc:
        n += len(json.dumps(tc, ensure_ascii=False))
    return n


def analyze(path):
    d = json.load(open(path, encoding="utf-8"))
    msgs = d["messages"]
    roles = collections.Counter(m.get("role") for m in msgs)
    cum_in = out = ncalls = 0
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant":
            ncalls += 1
            cum_in += sum(clen(x) for x in msgs[:i])
            out += clen(m)
    info = d.get("info", {}) or {}
    stats = info.get("model_stats", {}) or {}
    cfg = info.get("config", {}) or {}
    return {
        "inst": d.get("instance_id") or os.path.basename(path).split(".")[0],
        "roles": dict(roles),
        "assistant_msgs": ncalls,
        "api_calls": d.get("api_calls", stats.get("api_calls")),
        "cum_in": cum_in,
        "out": out,
        "logged_cost": d.get("total_cost", stats.get("instance_cost")),
        # 我方轨迹的键是 model_patch，mini 存在 info.submission —— 两边都要读，
        # 否则 mini 那边全算成 0（2026-09-17 第一版就犯了这个错，和 T10 是同一种「键名口径」bug）
        "patch_len": len(d.get("model_patch") or info.get("submission") or ""),
        "model": cfg.get("model", {}).get("model_name") if isinstance(cfg.get("model"), dict) else cfg.get("model"),
    }


def scan(subdir):
    """递归找 *.traj.json —— S2 的产物是扁平的，mini 2.4.6 写 <run>/<instance_id>/<instance_id>.traj.json。"""
    d = os.path.join(REPO, "results/inference", subdir)
    if not os.path.isdir(d):
        return []
    return [analyze(p) for p in sorted(glob.glob(os.path.join(d, "**", "*.traj.json"), recursive=True))]


def table(title, rows):
    print("=" * 78)
    print(title, " n =", len(rows))
    print("{:34s} {:>5s} {:>5s} {:>12s} {:>9s} {:>11s}".format(
        "instance", "asst", "api", "cum_in(chr)", "out(chr)", "logged$"))
    for r in rows:
        print("{:34s} {:>5d} {:>5s} {:>12,d} {:>9,d} {:>11s}".format(
            r["inst"], r["assistant_msgs"], str(r["api_calls"]),
            r["cum_in"], r["out"],
            "-" if r["logged_cost"] is None else "{:.5f}".format(r["logged_cost"])))
    tin = sum(r["cum_in"] for r in rows)
    tout = sum(r["out"] for r in rows)
    tcalls = sum(r["assistant_msgs"] for r in rows)
    print("-" * 78)
    print("TOTAL  assistant_msgs={}  cum_in={:,}  out={:,}".format(tcalls, tin, tout))
    return {"cum_in": tin, "out": tout, "calls": tcalls, "n": len(rows)}


def main():
    mini = scan("s2-baseline")
    mine = scan("s5-mine")
    m_tot = table("mini-SWE-agent  S2 baseline (09-06, 中转站, 2 条)", mini)
    s_tot = table("mine  S5 (09-17, DeepSeek 官方端点, 25 条)", mine)

    print("=" * 78)
    print("mini 的模型名（S2 config）:", {r["inst"]: r["model"] for r in mini})

    # S5 真实成本（余额差）→ 每百万字符的价（输入+输出合在一起算，见文件头口径）
    S5_YUAN = 5.27
    s5_chars = s_tot["cum_in"] + s_tot["out"]
    unit = S5_YUAN / (s5_chars / 1e6)
    print("\n[实测锚点] S5 余额差 ¥{:.2f} / {:,} 字符(输入累计+输出) = ¥{:.3f} / 百万字符".format(
        S5_YUAN, s5_chars, unit))

    # 配对：两条 S2 实例在我方 S5 里也有
    pair_ids = {r["inst"] for r in mini}
    mine_pair = [r for r in mine if r["inst"] in pair_ids]
    print("\n[配对] S2 的 2 条在 S5 里找到:", sorted(r["inst"] for r in mine_pair))
    if len(mine_pair) == len(mini):
        mp = sum(r["cum_in"] + r["out"] for r in mine_pair)
        kp = sum(r["cum_in"] + r["out"] for r in mini)
        ratio = kp / mp
        print("    同 2 条: mini {:,} 字符 vs 我方 {:,} 字符 -> 比值 {:.3f}".format(kp, mp, ratio))
        est_chars = s5_chars * ratio
        print("    [估法A 配对外推] mini 25 条 ≈ {:,.0f} 字符 -> ¥{:.2f}".format(
            est_chars, est_chars / 1e6 * unit))

    # 估法B：mini 的每条均值 × 25
    per = (m_tot["cum_in"] + m_tot["out"]) / m_tot["n"]
    print("    [估法B 均值×25]   mini 25 条 ≈ {:,.0f} 字符 -> ¥{:.2f}".format(
        per * 25, per * 25 / 1e6 * unit))

    # 估法C：只按调用次数比（不看上下文增长，故一定低估）
    print("    [估法C 仅调用数]  mini {:.1f} 次/条 vs 我方 {:.1f} 次/条".format(
        m_tot["calls"] / m_tot["n"], s_tot["calls"] / s_tot["n"]))

    # ---- 上限：S2 那 2 条只用了 11/20 步就收工，若 25 条里有实例一路跑到步数上限，账完全不同 ----
    # 模型：history 每步线性增长 g 字符 → 累计输入 cum_in ≈ 0.5·g·n²（等差数列求和）
    print("\n[上限] 按 mini 实测 history 增速反推（cum_in ≈ 0.5·g·n²，g 由该条自己的 cum_in 与步数解出）")
    gs = []
    for r in mini:
        g = 2 * r["cum_in"] / r["assistant_msgs"] ** 2
        gs.append(g)
        print("    {:34s} g = {:,.0f} 字符/步".format(r["inst"], g))
    gbar = sum(gs) / len(gs)
    print("    平均 g = {:,.0f} 字符/步（我方同法 = {:,.0f}）".format(
        gbar, sum(2 * r["cum_in"] / r["assistant_msgs"] ** 2 for r in mine) / len(mine)))
    for cap in (40, 250):
        per = 0.5 * gbar * cap ** 2
        print("    step_limit={:3d}: 单条跑满 {:>11,.0f} 字符 = ¥{:5.2f}  |  25 条全跑满 = ¥{:6.2f}".format(
            cap, per, per / 1e6 * unit, per * 25 / 1e6 * unit))

    # ---- 交叉验算：用 litellm 价格表回算 S5 的余额差，反推缓存命中率 ----
    # 价格【原文 litellm 1.100.0 model_cost["deepseek-flash"]，源注 api-docs.deepseek.com】，单位 $/百万 token
    P_MISS, P_HIT, P_OUT = 0.30, 0.006, 1.20
    CHARS_PER_TOKEN = 3.7   # 【判断】英文+代码的经验值，未实测；只用于量级核对
    FX = 7.1                # 【判断】¥/$ 约值
    in_tok = s_tot["cum_in"] / CHARS_PER_TOKEN
    out_tok = s_tot["out"] / CHARS_PER_TOKEN
    usd_in = S5_YUAN / FX - out_tok / 1e6 * P_OUT
    avg = usd_in / (in_tok / 1e6)
    hit = (P_MISS - avg) / (P_MISS - P_HIT)
    # ---- 跑后核算：同一把尺量「估得准不准」（s5-baseline 落盘后才有输出）----
    base = scan("s5-baseline")
    if base:
        b_tot = table("mini S5-baseline 实测（本次跑，step_limit=40）", base)
        act = b_tot["cum_in"] + b_tot["out"]
        est_a = s5_chars * (sum(r["cum_in"] + r["out"] for r in mini)
                            / sum(r["cum_in"] + r["out"] for r in mine_pair))
        print("=" * 78)
        print("[跑后核算] 字符量 估 {:,.0f} vs 实测 {:,.0f} -> 估/实 = {:.2f}".format(est_a, act, est_a / act))
        print("           按锚点折成钱 估 ¥{:.2f} vs 实测字符对应 ¥{:.2f}".format(
            est_a / 1e6 * unit, act / 1e6 * unit))
        print("           实际步数分布:", dict(collections.Counter(
            r["api_calls"] if r["api_calls"] is not None else r["assistant_msgs"] for r in base)))
        print("           跑满 40 步的条数:", sum(1 for r in base if r["assistant_msgs"] >= 40))
        print("           出 patch 的条数:", sum(1 for r in base if r["patch_len"] > 0), "/", len(base))
        if len(sys.argv) >= 3:
            spent = float(sys.argv[1]) - float(sys.argv[2])
            print("           余额差（跑前 {} - 跑后 {}）= ¥{:.2f}；估 ¥{:.2f} -> 估/实 = {:.2f}".format(
                sys.argv[1], sys.argv[2], spent, est_a / 1e6 * unit, est_a / 1e6 * unit / spent))

    print("\n[交叉验算] 若 {:.1f} 字符/token：S5 输入 {:,.0f} tok、输出 {:,.0f} tok".format(
        CHARS_PER_TOKEN, in_tok, out_tok))
    print("    全价不命中缓存本该 ¥{:.2f}，实际余额差 ¥{:.2f} -> 隐含缓存命中率 {:.0%}".format(
        in_tok / 1e6 * P_MISS * FX + out_tok / 1e6 * P_OUT * FX, S5_YUAN, hit))
    print("    -> 命中率落在 0~1 且偏高，与 append-only 会话的预期一致；估算沿用余额差反推的单价")
    print("    -> 若 mini 的命中率明显低于我方，实际会高于上面的点估（它每步重发全 history，同样是 append-only，预期接近）")


if __name__ == "__main__":
    sys.exit(main())
