import json, os, re

BASE = "/home/zixu/swe-bench-eval/results/inference/s5-baseline"
NET = re.compile(r"(urllib|requests\.get|urlopen|\bcurl\b|\bwget\b|api\.github\.com|github\.com|pip install|pip download|https?://)")
ids = sorted(d for d in os.listdir(BASE) if os.path.isdir(os.path.join(BASE, d)))

def flat(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n] + (" …" if len(s) > n else "")

tot_hit = 0
for iid in ids:
    p = "%s/%s/%s.traj.json" % (BASE, iid, iid)
    if not os.path.exists(p):
        print("MISSING", iid); continue
    d = json.load(open(p))
    hits = []
    turn = 0
    for m in d.get("messages", []):
        if m.get("role") != "assistant":
            continue
        turn += 1
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            try:
                a = json.loads(fn.get("arguments") or "{}")
            except Exception:
                a = {}
            c = a.get("command") or ""
            if NET.search(c):
                hits.append((turn, flat(c, 190)))
    if hits:
        tot_hit += 1
        print("\n##### %s  --  %d networked commands" % (iid, len(hits)))
        for t, c in hits[:6]:
            print("   T%-3d %s" % (t, c))
        if len(hits) > 6:
            print("   ... %d more" % (len(hits) - 6))
print("\n=== %d / %d instances issued at least one networked command ===" % (tot_hit, len(ids)))
