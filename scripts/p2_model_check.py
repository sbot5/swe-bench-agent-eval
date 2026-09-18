import json, pathlib, collections, hashlib

for run in ("s5-mine", "p2-mine", "p2-smoke"):
    models = collections.Counter()
    prompts = collections.Counter()
    for tf in sorted(pathlib.Path(f"results/inference/{run}").glob("*.traj.json")):
        d = json.loads(tf.read_text())
        for st in d.get("steps", []):
            models[st.get("returned_model")] += 1
        msgs = d.get("messages") or []
        if msgs and msgs[0].get("role") == "system":
            prompts[hashlib.md5(msgs[0]["content"].encode()).hexdigest()[:8]] += 1
    print(f"{run:12s} returned_model={dict(models)}")
    print(f"{'':12s} system prompt 指纹={dict(prompts)}")
