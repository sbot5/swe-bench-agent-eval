#!/usr/bin/env python3
"""p2_11138.py —— 读 django-11138 单条轨迹（EVAL-P2-groupA §九第 2 条的 $0 追查）。

问题：甲型（REPRO=0）的这一条，40 轮只调 4 次 run_python，新工具等于没加。到底在干什么？

只读 results/inference/{p2-mine,s5-mine}/django__django-11138.traj.json，不跑模型、不进容器。
用法：python3 scripts/p2_11138.py [head|rounds|thoughts|rpy|files|repeat|cmp|window|thoughtscan|thoughtgroup|gold|ctx]
      python3 scripts/p2_11138.py args <轮号...>     # 指定轮的完整 tool_args（rounds 会截断）
"""
import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
IID = "django__django-11138"


def load(run):
    p = ROOT / "results" / "inference" / run / (IID + ".traj.json")
    return json.loads(p.read_text(encoding="utf-8"))


def flat(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n] + ("…" if len(s) > n else "")


def argstr(step, n=52):
    a = step.get("tool_args") or {}
    return " ".join(f"{k}={flat(v, n)}" for k, v in a.items())


def cmd_head(d):
    steps = d["steps"]
    print(f"instance      {d['instance_id']}")
    print(f"stop_reason   {d['stop_reason']}   finish={d['finish_reason']!r} error={d['error']!r}")
    print(f"api_calls     {d['api_calls']}（模型轮数）   steps {len(steps)}（工具调用数）")
    print(f"model_patch   {len(d['model_patch'])} 字符")
    print(f"total_duration {d['total_duration']:.1f}s   total_cost {d['total_cost']}")
    pt = sum(s.get("prompt_tokens") or 0 for s in steps)
    ct = sum(s.get("completion_tokens") or 0 for s in steps)
    print(f"tokens        prompt {pt}  completion {ct}（注：同一轮多工具时逐 step 重复记同一轮的读数）")
    for k in ("cache_hit_tokens", "cache_miss_tokens", "reasoning_tokens"):
        if k in steps[0]:
            print(f"  {k:18s} {sum(s.get(k) or 0 for s in steps)}")
        else:
            print(f"  {k:18s} 【字段不存在】—— 该跑早于 ㉖ 的一行修")
    print()
    c = collections.Counter(s["tool_name"] for s in steps)
    for t, n in c.most_common():
        print(f"  {t:14s} {n:3d}")
    print()
    st = collections.Counter(s["status"] for s in steps)
    fc = collections.Counter(s.get("failure_category") for s in steps if s.get("failure_category"))
    print(f"status {dict(st)}   failure_category {dict(fc)}")
    rounds = sorted({s["index"] for s in steps})
    print(f"轮号范围 {min(rounds)}–{max(rounds)}，出现过的轮数 {len(rounds)}")
    per = collections.Counter(s["index"] for s in steps)
    multi = {r: n for r, n in sorted(per.items()) if n > 1}
    print(f"一轮多调的轮：{multi}")


def cmd_rounds(d):
    print(f"{'轮':>3s} {'#':>3s} {'tool':14s} {'st':3s} args | summary")
    for i, s in enumerate(d["steps"], 1):
        ok = "ok" if s["status"] == "ok" else s["status"][:3]
        print(f"{s['index']:3d} {i:3d} {s['tool_name']:14s} {ok:3s} {argstr(s)} | {flat(s.get('summary'), 88)}")


def cmd_thoughts(d):
    steps = d["steps"]
    ne = [(i, s) for i, s in enumerate(steps, 1) if (s.get("thought") or "").strip()]
    print(f"非空 thought：{len(ne)}/{len(steps)} 个 step\n")
    for i, s in ne:
        print(f"--- step {i} 轮 {s['index']} {s['tool_name']} ---")
        print((s["thought"] or "").strip())
        print()


def cmd_rpy(d):
    n = 0
    for i, s in enumerate(d["steps"], 1):
        if s["tool_name"] != "run_python":
            continue
        n += 1
        print(f"===== run_python #{n}  step {i} 轮 {s['index']}  status={s['status']} "
              f"failure={s.get('failure_category')} {s['duration']:.1f}s =====")
        print("--- code ---")
        print((s.get("tool_args") or {}).get("code", ""))
        print("--- summary（落盘的观察）---")
        print(s.get("summary"))
        print()
    print(f"合计 run_python {n} 次")


def cmd_files(d):
    rf = collections.Counter()
    order = []
    for s in d["steps"]:
        if s["tool_name"] != "read_file":
            continue
        a = s.get("tool_args") or {}
        key = (a.get("path"), a.get("start_line"), a.get("end_line"))
        rf[key] += 1
        order.append((s["index"], key, s["status"], flat(s.get("summary"), 60)))
    print(f"read_file 共 {sum(rf.values())} 次，去重后 {len(rf)} 个 (path,start,end)\n")
    byfile = collections.Counter()
    for (p, a, b), n in rf.items():
        byfile[p] += n
    print("按文件：")
    for p, n in byfile.most_common():
        print(f"  {n:3d}  {p}")
    print("\n重复的 (path,start,end)：")
    for k, n in rf.most_common():
        if n > 1:
            print(f"  {n}×  {k}")
    print("\n时序（轮 path start-end status summary）：")
    for r, (p, a, b), st, sm in order:
        print(f"  {r:3d} {str(p):58s} {str(a):>6s}-{str(b):<6s} {st:5s} {sm}")


def cmd_repeat(d):
    c = collections.Counter()
    for s in d["steps"]:
        c[(s["tool_name"], json.dumps(s.get("tool_args") or {}, sort_keys=True, ensure_ascii=False))] += 1
    dup = [(k, n) for k, n in c.items() if n > 1]
    tot = sum(n for _, n in dup)
    print(f"完全相同的 (tool,args) 调用：{len(dup)} 组，占用 {tot}/{len(d['steps'])} 次调用\n")
    for (t, a), n in sorted(dup, key=lambda x: -x[1]):
        print(f"  {n}×  {t:14s} {flat(a, 130)}")


def cmd_ctx(d):
    per = {}
    for s in d["steps"]:
        per.setdefault(s["index"], s.get("prompt_tokens"))  # 一轮多工具会重复落同一轮的读数，取第一次
    xs = sorted(per.items())
    print(f"逐轮 prompt token：轮 {xs[0][0]} = {xs[0][1]} → 轮 {xs[-1][0]} = {xs[-1][1]}")
    drops = [(i, prev, v) for (_, prev), (i, v) in zip(xs, xs[1:])
             if v is not None and prev is not None and v < prev]
    print(f"比上一轮少的轮：{len(drops)} 个（按降幅排序）")
    for i, prev, v in sorted(drops, key=lambda x: x[2] - x[1]):
        print(f"  轮 {i:2d}  {prev:6d} → {v:6d}  ({v - prev:+d})")


def cmd_args(d, rounds):
    for s in d["steps"]:
        if s["index"] in rounds:
            print(f"轮 {s['index']:2d} {s['tool_name']:12s} {json.dumps(s.get('tool_args') or {}, ensure_ascii=False)}")


def cmd_thoughtscan():
    """thought 全空是这一条的特例，还是整跑如此？顺带看 s5-mine 与 gold 回放。"""
    for run in ("p2-mine", "s5-mine"):
        d = ROOT / "results" / "inference" / run
        if not d.is_dir():
            print(f"{run}: 【目录不存在】")
            continue
        tot = ne = 0
        hits = []
        for p in sorted(d.glob("*.traj.json")):
            t = json.loads(p.read_text(encoding="utf-8"))
            steps = t.get("steps") or []
            n = sum(1 for s in steps if (s.get("thought") or "").strip())
            tot += len(steps)
            ne += n
            if n:
                hits.append((p.name.replace(".traj.json", ""), n, len(steps)))
        print(f"{run}: 非空 thought {ne}/{tot} step（{len(list(d.glob('*.traj.json')))} 条轨迹）")
        for iid, n, m in hits:
            print(f"    {iid:34s} {n}/{m}")


def cmd_window(run="p2-mine", keep_full=5):
    """C8 的滑窗（loop.py:310 trim_messages，只有最近 keep_full 条观察留全文）落到这一条上是什么样。

    gold 要改 4 个文件；问：任一时刻，窗口里最多同时有几个 gold 文件的**全文**？
    """
    gold = set()
    for s in load("gold-replay-s25")["steps"]:
        if s["tool_name"] == "apply_patch":
            gold.add((s.get("tool_args") or {}).get("path"))
    d = load(run)
    steps = d["steps"]
    best = (0, None)
    hist = []
    for i, s in enumerate(steps):
        win = steps[max(0, i - keep_full + 1):i + 1]
        strict, loose = set(), set()
        for w in win:
            p = (w.get("tool_args") or {}).get("path")
            if p in gold:
                loose.add(p)
                if w["tool_name"] == "read_file":
                    strict.add(p)
        hist.append((s["index"], len(strict), len(loose)))
        if len(strict) > best[0]:
            best = (len(strict), s["index"], sorted(strict))
    print(f"gold 改的 {len(gold)} 个文件：{sorted(gold)}")
    print(f"窗口 keep_full={keep_full}（loop.py:19 的 KEEP_FULL_OBSERVATIONS）\n")
    dist = collections.Counter(h[1] for h in hist)
    print(f"每个时刻窗口内「留着全文的 gold 文件」个数的分布（{len(hist)} 个时刻）：")
    for k in sorted(dist):
        print(f"  {k} 个：{dist[k]:3d} 次（{dist[k]/len(hist)*100:.0f}%）")
    print(f"\n峰值 {best[0]} 个，出现在轮 {best[1]}：{best[2]}")
    print(f"→ 从头到尾**没有任何一个时刻**窗口里同时留着全部 {len(gold)} 个 gold 文件的全文。"
          if best[0] < len(gold) else "→ 有时刻集齐过。")
    win = steps[-keep_full:]
    print(f"\n最后 {keep_full} 条观察（轮 {win[0]['index']}–{win[-1]['index']}，即收尾时模型手里还有全文的）：")
    for w in win:
        print(f"  轮 {w['index']:3d} {w['tool_name']:12s} {argstr(w, 60)}")


def _resolved(run, iid):
    p = ROOT / "results" / "evaluation" / run / (iid + ".report.json")
    if not p.is_file():
        return None
    r = json.loads(p.read_text(encoding="utf-8"))
    if iid in r and isinstance(r[iid], dict):
        r = r[iid]
    return bool(r.get("resolved"))


def cmd_thoughtgroup():
    """「thought 全空」是不是判别量？按 A/B 组（apply_patch==0）和 resolved 两跑并排看。"""
    for run in ("p2-mine", "s5-mine"):
        d = ROOT / "results" / "inference" / run
        rows = []
        for p in sorted(d.glob("*.traj.json")):
            iid = p.name.replace(".traj.json", "")
            t = json.loads(p.read_text(encoding="utf-8"))
            steps = t.get("steps") or []
            ap = sum(1 for s in steps if s["tool_name"] == "apply_patch")
            th = sum(1 for s in steps if (s.get("thought") or "").strip())
            rows.append((iid, "A" if ap == 0 else "B", _resolved(run, iid), th, len(steps)))
        print(f"=== {run} ===")
        for g in ("A", "B"):
            sub = [r for r in rows if r[1] == g]
            has = [r for r in sub if r[3] > 0]
            print(f"  {g} 组 {len(sub):2d} 条：有非空 thought 的 {len(has)}/{len(sub)}"
                  f"（{len(has)/len(sub)*100:.0f}%），thought step 合计 "
                  f"{sum(r[3] for r in sub)}/{sum(r[4] for r in sub)}")
        for label, want in (("RESOLVED", True), ("unresolved", False)):
            sub = [r for r in rows if r[2] is want]
            if not sub:
                continue
            has = [r for r in sub if r[3] > 0]
            print(f"  {label:10s} {len(sub):2d} 条：有非空 thought 的 {len(has)}/{len(sub)}"
                  f"（{len(has)/len(sub)*100:.0f}%）")
        zero = [r[0] for r in rows if r[3] == 0]
        print(f"  全程 0 thought 的 {len(zero)} 条：{', '.join(zero)}")
        print()


def cmd_gold(run="gold-replay-s25"):
    """gold patch 碰了哪些文件（从 gold 回放轨迹的 apply_patch 取）vs P2 这一跑读过哪些文件。"""
    g = load(run)
    touched = []
    for s in g["steps"]:
        if s["tool_name"] != "apply_patch":
            continue
        touched.append((s.get("tool_args") or {}).get("path"))
    gold_files = collections.Counter(touched)
    print(f"gold 回放（{run}）：apply_patch {len(touched)} 次，涉及 {len(gold_files)} 个文件")
    for f, n in gold_files.most_common():
        print(f"  {n:2d} hunk  {f}")

    d = load("p2-mine")
    read = collections.Counter()
    for s in d["steps"]:
        if s["tool_name"] == "read_file":
            read[(s.get("tool_args") or {}).get("path")] += 1
    print(f"\nP2 这一跑 read_file 命中的文件（{len(read)} 个）：")
    for f, n in read.most_common():
        mark = "  ← gold 改过" if f in gold_files else ""
        print(f"  {n:2d}×  {f}{mark}")
    cov = [f for f in gold_files if f in read]
    print(f"\ngold 改过的 {len(gold_files)} 个文件里，P2 读到了 {len(cov)} 个：{cov}")
    miss = [f for f in gold_files if f not in read]
    print(f"没读到的：{miss}")


def cmd_cmp():
    print(f"{'run':10s} {'stop':12s} {'轮':>4s} {'steps':>6s} {'patch':>6s} {'时长':>7s}  工具分布")
    for run in ("s5-mine", "p2-mine"):
        try:
            d = load(run)
        except FileNotFoundError:
            print(f"{run:10s} 【未找到轨迹】")
            continue
        c = collections.Counter(s["tool_name"] for s in d["steps"])
        dist = " ".join(f"{t}={n}" for t, n in c.most_common())
        print(f"{run:10s} {d['stop_reason']:12s} {d['api_calls']:4d} {len(d['steps']):6d} "
              f"{len(d['model_patch']):6d} {d['total_duration']:7.1f}  {dist}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "head"
    if cmd == "cmp":
        return cmd_cmp()
    if cmd == "window":
        return cmd_window(*sys.argv[2:3])
    if cmd == "thoughtgroup":
        return cmd_thoughtgroup()
    if cmd == "thoughtscan":
        return cmd_thoughtscan()
    if cmd == "gold":
        return cmd_gold(*sys.argv[2:3])
    if cmd == "args":
        return cmd_args(load("p2-mine"), {int(x) for x in sys.argv[2:]})
    run = sys.argv[2] if len(sys.argv) > 2 else "p2-mine"
    d = load(run)
    {"head": cmd_head, "rounds": cmd_rounds, "thoughts": cmd_thoughts,
     "rpy": cmd_rpy, "files": cmd_files, "repeat": cmd_repeat, "ctx": cmd_ctx}[cmd](d)


if __name__ == "__main__":
    main()
