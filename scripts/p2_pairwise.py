"""P2 vs S5 配对：⑪ 的判别量逐条对照 + 工具使用分布。
用法：p2_pairwise.py <new-run-dir> <old-run-dir>
"""
import json, sys, collections, pathlib


def scan(run: pathlib.Path):
    out = {}
    for tf in sorted(run.glob("*.traj.json")):
        data = json.loads(tf.read_text())
        counts = collections.Counter()
        first_patch = None
        for i, st in enumerate(data.get("steps", []), 1):
            name = st.get("tool") or st.get("name") or st.get("tool_name")
            counts[name] += 1
            if name == "apply_patch" and first_patch is None:
                first_patch = i
        out[data["instance_id"]] = {
            "n_patch": counts.get("apply_patch", 0),
            "first": first_patch,
            "api": data.get("api_calls"),
            "steps": len(data.get("steps", [])),
            "plen": len(data.get("model_patch") or ""),
            "stop": data.get("stop_reason"),
            "err": data.get("error"),
            "tools": counts,
        }
    return out


new = scan(pathlib.Path(sys.argv[1]))
old = scan(pathlib.Path(sys.argv[2]))
old_a = {k for k, v in old.items() if v["n_patch"] == 0}

print(f"新 n={len(new)}  旧 n={len(old)}  旧 A 组 {len(old_a)} 条\n")
fmt = "{:38s} {:>10s} {:>10s} {:>8s} {:>8s} {:>4s}"
print(fmt.format("instance", "旧 first/n", "新 first/n", "旧 plen", "新 plen", "组"))
print("-" * 86)
moved = []
for k in sorted(set(new) | set(old)):
    o, n = old.get(k), new.get(k)
    def cell(v):
        if v is None:
            return "-"
        return f"{'从未' if v['first'] is None else v['first']}/{v['n_patch']}"
    grp = "A" if k in old_a else "B"
    print(fmt.format(k, cell(o), cell(n),
                     str(o["plen"]) if o else "-", str(n["plen"]) if n else "-", grp))
    if k in old_a and n and n["n_patch"] > 0:
        moved.append(k)

print(f"\n>>> A 组挪开的（原 apply_patch=0，本次 >0）：{len(moved)}/{len(old_a)} 条")
for k in moved:
    print(f"    {k:38s} 首次动手步号={new[k]['first']} 调用={new[k]['n_patch']} patch={new[k]['plen']}ch")

print("\n=== 工具使用分布（全 25 条合计）===")
for label, d in (("S5", old), ("P2", new)):
    tot = collections.Counter()
    for v in d.values():
        tot.update(v["tools"])
    print(f"  {label}: {dict(tot.most_common())}")

print("\n=== 健康度 ===")
for label, d in (("S5", old), ("P2", new)):
    empty = sum(1 for v in d.values() if v["plen"] == 0)
    errs = sum(1 for v in d.values() if v["err"])
    stops = collections.Counter(v["stop"] for v in d.values())
    print(f"  {label}: 落盘 {len(d)}  空 patch {empty}  error {errs}  stop={dict(stops)}")

rp = collections.Counter()
for k, v in new.items():
    rp[v["tools"].get("run_python", 0) > 0] += 1
print(f"\n=== P2 里用过 run_python 的实例：{rp[True]}/{len(new)} ===")
