#!/usr/bin/env python3
"""S5 badcase 归因：撞 max_steps 的 12 条，40 轮里到底在干什么。

只读 results/inference/s5-mine/*.traj.json，不跑模型、不改 agent/。
输出两部分：① 全 25 条的工具与失败分布 ② 12 条 max_steps 的逐条剖面。
"""
import json
import sys
from collections import Counter
from pathlib import Path

D = Path.home() / "swe-bench-eval/results/inference/s5-mine"


def load(p):
    return json.load(open(p, encoding="utf-8"))


def argkey(step):
    """(工具, 规范化参数) —— 用来找完全重复的调用。"""
    return (step["tool_name"], json.dumps(step.get("tool_args") or {}, sort_keys=True))


def brief(step, n=90):
    a = step.get("tool_args") or {}
    # 只挑能认出「在看哪儿」的字段
    bits = []
    for k in ("path", "pattern", "query", "old_string", "command", "test_files"):
        if k in a:
            v = str(a[k]).replace("\n", "\\n")
            bits.append(f"{k}={v[:60]}")
    return " ".join(bits)[:n]


def profile(d):
    steps = d["steps"]
    tools = Counter(s["tool_name"] for s in steps)
    status = Counter(s["status"] for s in steps)
    fails = Counter(s["failure_category"] for s in steps if s.get("failure_category"))

    # 重复调用：同一 (工具,参数) 出现过不止一次
    keys = [argkey(s) for s in steps]
    kc = Counter(keys)
    dup_calls = sum(c - 1 for c in kc.values() if c > 1)  # 重复了多少步
    dup_top = [(k[0], json.loads(k[1]), c) for k, c in kc.most_common() if c > 1]

    # 编辑类工具（真正能改文件的）
    EDITS = {"edit_file", "create_file", "apply_patch", "write_file", "str_replace"}
    edits = [s for s in steps if s["tool_name"] in EDITS]
    edit_ok = [s for s in edits if s["status"] == "ok"]

    # 最后一次编辑尝试落在第几步（占全程多少）
    last_edit = edits[-1]["index"] if edits else None
    return dict(
        steps=len(steps), tools=tools, status=status, fails=fails,
        dup_calls=dup_calls, dup_top=dup_top,
        n_edit=len(edits), n_edit_ok=len(edit_ok), last_edit=last_edit,
    )


def main():
    files = sorted(D.glob("*.traj.json"))
    rows = [(f.stem.replace(".traj", ""), load(f)) for f in files]

    print("=" * 78)
    print("① 全 25 条：工具使用与失败分布")
    print("=" * 78)
    all_tools, all_status, all_fails = Counter(), Counter(), Counter()
    for _, d in rows:
        p = profile(d)
        all_tools += p["tools"]; all_status += p["status"]; all_fails += p["fails"]
    print("工具调用总计:", dict(all_tools.most_common()))
    print("状态总计    :", dict(all_status.most_common()))
    print("失败分类总计:", dict(all_fails.most_common()) or "（无）")

    hit = [(i, d) for i, d in rows if d["stop_reason"] == "max_steps"]
    print()
    print("=" * 78)
    print(f"② 撞 max_steps 的 {len(hit)} 条逐条剖面")
    print("=" * 78)
    for iid, d in hit:
        p = profile(d)
        tag = "空patch" if not d["model_patch"] else f"patch={len(d['model_patch'])}"
        print()
        print(f"--- {iid}  [{tag}]  steps={p['steps']} calls={d['api_calls']} "
              f"{d['total_duration']:.0f}s ---")
        print(f"  工具: {dict(p['tools'].most_common())}")
        print(f"  状态: {dict(p['status'].most_common())}"
              + (f"  失败分类: {dict(p['fails'])}" if p["fails"] else ""))
        print(f"  编辑类调用: {p['n_edit']} 次（成功 {p['n_edit_ok']}）"
              f"  最后一次编辑在第 {p['last_edit']} 步" if p["n_edit"]
              else "  编辑类调用: 0 次 —— 全程没试过改文件")
        print(f"  完全重复的调用: {p['dup_calls']} 步 / {p['steps']} 步"
              f" = {p['dup_calls']/p['steps']*100:.0f}%")
        for tn, ta, c in p["dup_top"][:4]:
            s = json.dumps(ta, ensure_ascii=False)[:70]
            print(f"      x{c}  {tn}({s})")
        print("  最后 6 步:")
        for s in d["steps"][-6:]:
            print(f"      {s['index']:>3} {s['tool_name']:<14} {s['status']:<8} {brief(s)}")


if __name__ == "__main__":
    main()
