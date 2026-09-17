import json, os, re
# P1 冒烟核查：模型真的被调用了吗？联网尝试的"结果"是什么？（判据是 0 条成功取件，不是 0 条尝试）
P = "/home/zixu/swe-bench-eval/results/inference/s5-nonet-smoke/django__django-11138/django__django-11138.traj.json"
d = json.load(open(P))
msgs = d.get("messages", [])
info = d.get("info", {})

roles = {}
for m in msgs:
    roles[m.get("role")] = roles.get(m.get("role"), 0) + 1
print("messages by role:", roles)
print("exit_status:", (info.get("exit_status") or json.dumps(info)[:200]))
print("model_stats:", json.dumps(info.get("model_stats", {}))[:300])
sub = info.get("submission") or ""
print("submission chars:", len(sub))

NET = re.compile(r"(urllib|requests\.get|urlopen|\bcurl\b|\bwget\b|github\.com|pip install|pip download|https?://|git fetch|git ls-remote|git clone)")
turn = 0
hits = 0
for i, m in enumerate(msgs):
    if m.get("role") != "assistant":
        continue
    turn += 1
    for tc in (m.get("tool_calls") or []):
        try:
            a = json.loads((tc.get("function") or {}).get("arguments") or "{}")
        except Exception:
            a = {}
        c = a.get("command") or ""
        if NET.search(c):
            hits += 1
            # 找紧随其后的 user/tool 观察，看这次尝试的结果
            obs = ""
            for n in msgs[i+1:i+3]:
                if n.get("role") in ("user", "tool"):
                    obs = n.get("content") or ""
                    break
            if isinstance(obs, list):
                obs = " ".join(str(x) for x in obs)
            flat = lambda s, n: re.sub(r"\s+", " ", s or "").strip()[:n]
            print("\n  T%-3d CMD: %s" % (turn, flat(c, 160)))
            print("       OBS: %s" % flat(obs, 260))
print("\n=== 联网尝试 %d 次；模型轮数 %d ===" % (hits, turn))
