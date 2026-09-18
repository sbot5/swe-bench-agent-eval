import json, pathlib, collections

def show(run, iid, label):
    d = json.loads(pathlib.Path(f"results/inference/{run}/{iid}.traj.json").read_text())
    steps = d.get("steps", [])
    c = collections.Counter(s["tool_name"] for s in steps)
    first_rp = next((s["index"] for s in steps if s["tool_name"] == "run_python"), None)
    first_ap = next((s["index"] for s in steps if s["tool_name"] == "apply_patch"), None)
    first_rt = next((s["index"] for s in steps if s["tool_name"] == "run_tests"), None)
    print(f"--- {label}: {run}/{iid}")
    print(f"    tools={dict(c)}  轮数={d.get('api_calls')}  stop={d.get('stop_reason')}  patch={len(d.get('model_patch') or '')}ch")
    print(f"    首次 run_python=轮{first_rp}  首次 run_tests=轮{first_rt}  首次 apply_patch=轮{first_ap}")
    errs = collections.Counter(s["failure_category"] for s in steps if s["status"] != "ok")
    print(f"    非 ok 状态: {dict(errs) if errs else '无'}")

show("s5-mine", "django__django-14631", "A 组唯一挪开的 · S5(空 patch)")
show("p2-mine", "django__django-14631", "A 组唯一挪开的 · P2(4197ch, RESOLVED)")
print()
show("s5-mine", "sphinx-doc__sphinx-9711", "反向丢掉的 · S5(1294ch, RESOLVED)")
show("p2-mine", "sphinx-doc__sphinx-9711", "反向丢掉的 · P2(空 patch)")

print("\n=== P2 里 run_python 的调用规模 ===")
lens = []
for tf in pathlib.Path("results/inference/p2-mine").glob("*.traj.json"):
    d = json.loads(tf.read_text())
    for s in d.get("steps", []):
        if s["tool_name"] == "run_python":
            lens.append(len(str(s["tool_args"].get("code", ""))))
lens.sort()
print(f"  n={len(lens)}  code 长度 中位={lens[len(lens)//2]}  p90={lens[int(len(lens)*0.9)]}  max={lens[-1]}")
ok = sum(1 for tf in pathlib.Path("results/inference/p2-mine").glob("*.traj.json")
         for s in json.loads(tf.read_text()).get("steps", [])
         if s["tool_name"] == "run_python" and s["status"] == "ok")
print(f"  status=ok: {ok}/{len(lens)}")
