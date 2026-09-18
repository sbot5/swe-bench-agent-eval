"""⑪ 的判别量：每实例的 apply_patch 调用数与首次动手步号。
比总分更能说明问题 —— S5 的 A 组是 apply_patch=0 / 首次动手「从未」。
用法：p2_discriminant.py <run-dir> [<对照 run-dir>]
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
            "apply_patch": counts.get("apply_patch", 0),
            "run_python": counts.get("run_python", 0),
            "run_tests": counts.get("run_tests", 0),
            "first_patch_step": first_patch,
            "api_calls": data.get("api_calls"),
            "steps": len(data.get("steps", [])),
            "patch_len": len(data.get("model_patch") or ""),
            "stop": data.get("stop_reason"),
            "tools": dict(counts),
        }
    return out


base = scan(pathlib.Path(sys.argv[1]))
print(f"=== {sys.argv[1]}  n={len(base)} ===")
a_group = [k for k, v in base.items() if v["apply_patch"] == 0]
print(f"A 组（apply_patch=0，从未动手）{len(a_group)} 条:")
for k in sorted(a_group):
    v = base[k]
    print(f"  {k:38s} steps={v['steps']:3d} api={v['api_calls']:3d} stop={v['stop']}")
print(f"\nB 组（出手了）{len(base)-len(a_group)} 条，首次动手步号:")
for k in sorted(base):
    v = base[k]
    if v["apply_patch"]:
        print(f"  {k:38s} first={v['first_patch_step']:3d} n_patch={v['apply_patch']:2d} patch_len={v['patch_len']:5d}")
