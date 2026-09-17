import json, os, re

ROOT = "/home/zixu/swe-bench-eval"
INF = ROOT + "/results/inference"
EV = ROOT + "/results/evaluation"

os.environ["HF_DATASETS_OFFLINE"] = "1"
from datasets import load_dataset
ds = {r["instance_id"]: r for r in load_dataset("SWE-bench/SWE-bench_Verified", split="test")}

GOLD_FETCH = re.compile(r"(\.patch\b|\.diff\b|/pulls/\d+/files|/commits/[0-9a-f]{7,40}|pull/\d+)")
NET = re.compile(r"(urllib|requests\.get|urlopen|\bcurl\b|\bwget\b|api\.github\.com|raw\.githubusercontent|github\.com|pip download|git ls-remote|git clone)")

def lines(patch, sign):
    out = set()
    for ln in (patch or "").splitlines():
        if ln.startswith(sign) and not ln.startswith(sign * 3):
            s = re.sub(r"\s+", " ", ln[1:]).strip()
            if s:
                out.add(s)
    return out

def overlap(pred, gold):
    ga, gr = lines(gold, "+"), lines(gold, "-")
    pa, pr = lines(pred, "+"), lines(pred, "-")
    if not ga:
        return None
    rec = len(ga & pa) / len(ga)
    prec = len(ga & pa) / len(pa) if pa else 0.0
    rec_r = len(gr & pr) / len(gr) if gr else None
    return rec, prec, rec_r, len(ga), len(pa)

def resolved(run, iid):
    p = "%s/%s/%s.report.json" % (EV, run, iid)
    if not os.path.exists(p):
        return "?"
    d = json.load(open(p))
    r = d.get(iid) or d
    return "Y" if r.get("resolved") else "n"

ids = sorted(ds)
ids = [i for i in ids if os.path.exists("%s/s5-mine/%s.traj.json" % (INF, i))]

print("%-32s | %-14s | %-14s | net gold-fetch" % ("instance", "MINI rec/prec", "MINE rec/prec"))
print("-" * 96)
rows = []
for iid in ids:
    gold = ds[iid]["patch"]
    b = json.load(open("%s/s5-baseline/%s/%s.traj.json" % (INF, iid, iid)))
    mini_patch = (b.get("info") or {}).get("submission") or ""
    mine_patch = json.load(open("%s/s5-mine/%s.traj.json" % (INF, iid)))["model_patch"] or ""
    nfetch, ngold = 0, 0
    for m in b.get("messages", []):
        if m.get("role") != "assistant":
            continue
        for tc in (m.get("tool_calls") or []):
            c = ""
            try:
                c = json.loads((tc.get("function") or {}).get("arguments") or "{}").get("command") or ""
            except Exception:
                pass
            if NET.search(c):
                nfetch += 1
                if GOLD_FETCH.search(c):
                    ngold += 1
    o1, o2 = overlap(mini_patch, gold), overlap(mine_patch, gold)
    f = lambda o: "  --  " if not o else "%.2f/%.2f" % (o[0], o[1])
    print("%-32s | %s %s | %s %s | net=%-3d goldish=%d"
          % (iid, resolved("s5-baseline", iid), f(o1), resolved("s5-mine", iid), f(o2), nfetch, ngold))
    rows.append((iid, resolved("s5-baseline", iid), o1, resolved("s5-mine", iid), o2, nfetch, ngold))

print("\n=== aggregates ===")
mr = [r[2][0] for r in rows if r[2] and r[1] == "Y"]
nr = [r[4][0] for r in rows if r[4] and r[3] == "Y"]
print("MINI resolved: n=%d  mean added-line recall vs gold = %.3f  (exact>=0.9: %d)"
      % (len(mr), sum(mr) / len(mr) if mr else 0, sum(1 for x in mr if x >= 0.9)))
print("MINE resolved: n=%d  mean added-line recall vs gold = %.3f  (exact>=0.9: %d)"
      % (len(nr), sum(nr) / len(nr) if nr else 0, sum(1 for x in nr if x >= 0.9)))
