"""P2 原样重跑（p2-rerun）与 P2（p2-mine）、S5（s5-mine）的对照。2026-09-19。

子命令：
  resolved  三跑 resolved 集合与换位（判定用 resolved_ids 白名单，⑩；分母写 /25）
  groupa    A 组 9 条（S5 的 apply_patch=0）在 P2 与重跑里的首次动手
  cache     ㉖ 三列直读：总命中率、第 1 轮的跨跑命中、C8 滑窗的逐轮预测检验
  tokens    去重后的输入/输出 token（按 step['index'] 去重，同 p2_tokens.py），配余额差算单价
  diverge   同配置两跑（p2-mine vs p2-rerun）的轨迹从第几次工具调用开始分叉
  never     三跑各自「从未 apply_patch」的实例集合

用法：PYTHONPATH=. .venv/bin/python scripts/p2_rerun_compare.py <子命令>
"""
import collections
import json
import pathlib
import statistics
import sys

RUNS = ("s5-mine", "p2-mine", "p2-rerun")
GROUP_A = (  # 【原文 docs/EVAL-P2.md §三】S5 那 9 条 apply_patch=0
    "django__django-14631", "django__django-10554", "django__django-11138",
    "pylint-dev__pylint-4551", "pylint-dev__pylint-8898", "sphinx-doc__sphinx-11510",
    "sphinx-doc__sphinx-8638", "sympy__sympy-17630", "sympy__sympy-18211",
)
KEEP_FULL = 5  # 【原文 DESIGN-loop.md C8】保留最近 5 条完整观察


def results_json(run):
    for base in ("results/evaluation", "logs/evaluation"):
        p = pathlib.Path(base) / run / "results.json"
        if p.exists():
            return json.loads(p.read_text())
    sys.exit(f"找不到 {run} 的 results.json")


def trajs(run):
    ds = [json.loads(tf.read_text()) for tf in sorted(pathlib.Path(f"results/inference/{run}").glob("*.traj.json"))]
    return {d["instance_id"]: d for d in ds}


def turns_of(d):
    """按模型轮去重：{index: 该轮第一条 StepRecord}，以及每轮之前累计的 tool 消息数。"""
    turns, calls_before, seen_calls = {}, {}, 0
    for st in d["steps"]:
        if st["index"] not in turns:
            turns[st["index"]] = st
            calls_before[st["index"]] = seen_calls
        seen_calls += 1
    return turns, calls_before


def cmd_resolved():
    res = {r: results_json(r) for r in RUNS}
    tr = {r: trajs(r) for r in RUNS}
    print(f"{'':<26}" + "".join(f"{r:>12}" for r in RUNS))
    for key in ("submitted_instances", "resolved_instances", "empty_patch_instances",
                "infra_failure_instances", "ambiguous_failure_instances", "error_instances"):
        print(f"{key:<26}" + "".join(f"{res[r][key]!s:>12}" for r in RUNS))
    for r in RUNS:
        stops = collections.Counter(d.get("stop_reason") for d in tr[r].values())
        has_patch_unres = len(set(res[r]["submitted_ids"]) - set(res[r]["resolved_ids"]) - set(res[r]["empty_patch_ids"]))
        print(f"{r}: 有 patch 但没过 {has_patch_unres} · stop_reason {dict(stops)} · 落盘 traj {len(tr[r])}")
    ok = {r: set(res[r]["resolved_ids"]) for r in RUNS}
    a, b = ok["p2-mine"], ok["p2-rerun"]
    print(f"\nP2 vs 重跑：两边都过 {len(a & b)} · 只有 P2 过 {len(a - b)} {sorted(a - b)} · 只有重跑过 {len(b - a)} {sorted(b - a)}")
    allids = sorted(set(res["p2-rerun"]["submitted_ids"]) | set(res["p2-mine"]["submitted_ids"]))
    print(f"\n{'instance':<34}" + "".join(f"{r:>10}" for r in RUNS) + "   三跑都过/都不过/摇摆")
    swing = collections.Counter()
    for i in allids:
        marks = ["R" if i in ok[r] else ("·" if i in res[r]["empty_patch_ids"] else "x") for r in RUNS]
        n = sum(m == "R" for m in marks)
        kind = "都过" if n == 3 else ("都不过" if n == 0 else "摇摆")
        swing[kind] += 1
        print(f"{i:<34}" + "".join(f"{m:>10}" for m in marks) + f"   {kind}")
    print("（R = resolved · x = 有 patch 没过 · · = 空 patch）", dict(swing))


def first_patch(d):
    for n, st in enumerate(d["steps"], 1):
        if st.get("tool_name") == "apply_patch":
            return f"轮 {st['index']} / 第 {n} 次调用"
    return "从未"


def cmd_groupa():
    res = {r: set(results_json(r)["resolved_ids"]) for r in ("p2-mine", "p2-rerun")}
    tr = {r: trajs(r) for r in ("p2-mine", "p2-rerun")}
    print(f"{'instance':<28}{'P2 首次 apply_patch':>24}{'次':>4}{'过':>4}{'重跑 首次 apply_patch':>26}{'次':>4}{'过':>4}")
    moved = 0
    for i in GROUP_A:
        row = []
        for r in ("p2-mine", "p2-rerun"):
            d = tr[r][i]
            k = sum(st.get("tool_name") == "apply_patch" for st in d["steps"])
            row += [first_patch(d), k, "R" if i in res[r] else "-"]
        moved += row[3] != "从未"
        print(f"{i:<28}{row[0]:>24}{row[1]:>4}{row[2]:>4}{row[3]:>26}{row[4]:>4}{row[5]:>4}")
    print(f"\n重跑里 A 组动了手的: {moved}/9")


def cmd_cache():
    tr = trajs("p2-rerun")
    tot = collections.Counter()
    first_turn, pre, post = [], [], []
    first_abs, first_rows = collections.Counter(), []  # 第 1 轮 hit 的绝对值：全都一样 = 只命中共用的 system+工具前缀
    for i, d in sorted(tr.items()):
        turns, calls_before = turns_of(d)
        prev_prompt = None
        for k in sorted(turns):
            st = turns[k]
            hit, miss, p = st.get("cache_hit_tokens"), st.get("cache_miss_tokens"), st["prompt_tokens"]
            if hit is None or miss is None:
                tot["none"] += 1
                prev_prompt = p
                continue
            tot["hit"] += hit
            tot["miss"] += miss
            tot["prompt"] += p
            tot["turns"] += 1
            if prev_prompt is None:
                first_turn.append(hit / p)
                first_abs[hit] += 1
                first_rows.append((i, p, hit))
                tot["first_hit"] += hit
                tot["first_prompt"] += p
            else:
                ratio = hit / prev_prompt
                if calls_before[k] <= KEEP_FULL:
                    pre.append(ratio)
                    tot["pre_miss"] += miss
                else:
                    post.append(ratio)
                    tot["post_miss"] += miss
            prev_prompt = p
    print(f"有读数的轮 {tot['turns']} · None 轮 {tot['none']}")
    print(f"总命中率 hit/prompt = {tot['hit']:,} / {tot['prompt']:,} = {tot['hit'] / tot['prompt']:.1%}")
    print(f"第 1 轮（跨跑缓存）: {len(first_turn)} 条，合计 {tot['first_hit']:,}/{tot['first_prompt']:,} = "
          f"{tot['first_hit'] / tot['first_prompt']:.1%}；逐条 min {min(first_turn):.0%} 中位 {statistics.median(first_turn):.0%} max {max(first_turn):.0%}")
    print(f"  第 1 轮 hit 的绝对值分布: {dict(first_abs)}")
    print(f"  第 1 轮 prompt 范围: {min(r[1] for r in first_rows):,} ~ {max(r[1] for r in first_rows):,}")

    def dist(xs):
        xs = sorted(xs)
        q = lambda f: xs[min(len(xs) - 1, int(f * len(xs)))]
        return f"n={len(xs)} min {xs[0]:.0%} p10 {q(0.1):.0%} 中位 {statistics.median(xs):.0%} p90 {q(0.9):.0%} max {xs[-1]:.0%}"

    print(f"\nC8 预测检验（hit / 上一轮 prompt）：")
    print(f"  之前累计观察 ≤{KEEP_FULL}（不折叠，应≈100%）: {dist(pre)}")
    print(f"  之前累计观察 >{KEEP_FULL}（每轮新折叠一条，应大跌）: {dist(post)}")
    print(f"  ≥90% 的占比：不折叠组 {sum(x >= 0.9 for x in pre) / len(pre):.0%} · 折叠组 {sum(x >= 0.9 for x in post) / len(post):.0%}")
    print(f"  miss token 落在哪：第 1 轮 {tot['first_prompt'] - tot['first_hit']:,} · 不折叠组 {tot['pre_miss']:,} · "
          f"折叠组 {tot['post_miss']:,}（占全部 miss {tot['post_miss'] / tot['miss']:.0%}）")


def cmd_tokens():
    print(f"{'run':<18}{'条':>4}{'输入 tok':>13}{'输出 tok':>11}{'去重轮':>8}{'api_calls':>11}")
    for r in ("p2-smoke", "p2-mine", "p2-rerun-smoke", "p2-rerun"):
        tr = trajs(r)
        i = o = t = calls = 0
        for d in tr.values():
            turns, _ = turns_of(d)
            i += sum(st["prompt_tokens"] for st in turns.values())
            o += sum(st["completion_tokens"] for st in turns.values())
            t += len(turns)
            calls += d.get("api_calls") or 0
        print(f"{r:<18}{len(tr):>4}{i:>13,}{o:>11,}{t:>8,}{calls:>11,}")


def cmd_diverge():
    """同配置两跑的轨迹从第几次工具调用开始不同：比 (tool_name, tool_args) 序列的公共前缀长度。
    请求写的是 temperature=0.0（model.py:38），但 drop_params=True 时供应商不吃会被静默丢掉 —— 生没生效看这里。"""
    a, b = trajs("p2-mine"), trajs("p2-rerun")
    rows = []
    for i in sorted(a):
        sa = [(st.get("tool_name"), json.dumps(st.get("tool_args"), sort_keys=True)) for st in a[i]["steps"]]
        sb = [(st.get("tool_name"), json.dumps(st.get("tool_args"), sort_keys=True)) for st in b[i]["steps"]]
        n = 0
        while n < min(len(sa), len(sb)) and sa[n] == sb[n]:
            n += 1
        rows.append((i, n, len(sa), len(sb), a[i]["model_patch"] == b[i]["model_patch"] and bool(a[i]["model_patch"])))
    print(f"{'instance':<34}{'公共前缀(次调用)':>16}{'P2 总调用':>10}{'重跑 总调用':>11}{'patch 逐字相同':>14}")
    for r in rows:
        print(f"{r[0]:<34}{r[1]:>16}{r[2]:>10}{r[3]:>11}{'是' if r[4] else '':>14}")
    ns = [r[1] for r in rows]
    print(f"\n公共前缀：0 次（第一次调用就不同）{sum(n == 0 for n in ns)} 条 · 中位 {statistics.median(ns)} · max {max(ns)}")
    print(f"patch 逐字相同（非空）: {sum(r[4] for r in rows)} 条")


def cmd_never():
    """三跑各自「从未 apply_patch」的实例集合 —— A 组之外有没有人掉进来、A 组里有没有人出去。"""
    sets = {}
    for r in RUNS:
        sets[r] = {i for i, d in trajs(r).items() if not any(st.get("tool_name") == "apply_patch" for st in d["steps"])}
        print(f"{r:<10} 从未动手 {len(sets[r])} 条：A 组内 {len(sets[r] & set(GROUP_A))} · A 组外 {sorted(sets[r] - set(GROUP_A))}")
    common = set.intersection(*sets.values())
    print(f"三跑都从未动手: {len(common)} 条 {sorted(common)}")


{"resolved": cmd_resolved, "groupa": cmd_groupa, "cache": cmd_cache, "tokens": cmd_tokens,
 "diverge": cmd_diverge, "never": cmd_never}[sys.argv[1]]()
