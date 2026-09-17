import json, os, re
# P1 三方分层对比：mini-有网(s5-baseline) / mini-断网(s5-baseline-nonet) / 我方(s5-mine)。
# 沿用 baseline_gold_strat.py 的分层与指标（gold 新增行集合的 recall），加一列断网组，
# 并把「有 patch 但 unresolved」单列 —— 有网 mini 这一档是 0 条。2026-09-17。
ROOT = "/home/zixu/swe-bench-eval"; INF = ROOT + "/results/inference"; EV = ROOT + "/results/evaluation"
os.environ["HF_DATASETS_OFFLINE"] = "1"
from datasets import load_dataset
ds = {r["instance_id"]: r for r in load_dataset("SWE-bench/SWE-bench_Verified", split="test")}

def add_lines(p):
    return {re.sub(r"\s+", " ", l[1:]).strip() for l in (p or "").splitlines()
            if l.startswith("+") and not l.startswith("+++") and l[1:].strip()}

def res(run, iid):
    p = "%s/%s/%s.report.json" % (EV, run, iid)
    if not os.path.exists(p): return False
    d = json.load(open(p)); return bool((d.get(iid) or d).get("resolved"))

def mini_patch(run, iid):
    p = "%s/%s/%s/%s.traj.json" % (INF, run, iid, iid)
    if not os.path.exists(p): return None
    return (json.load(open(p)).get("info") or {}).get("submission") or ""

def mine_patch(iid):
    p = "%s/s5-mine/%s.traj.json" % (INF, iid)
    if not os.path.exists(p): return None
    return json.load(open(p)).get("model_patch") or ""

ids = sorted(i for i in ds if os.path.exists("%s/s5-mine/%s.traj.json" % (INF, i)))
rows = []
print("%-30s %5s | %-14s | %-14s | %-14s" % ("instance", "gold+", "MINI-NET", "MINI-NONET", "MINE"))
print("%-30s %5s | %-14s | %-14s | %-14s" % ("", "", "res recall", "res recall", "res recall"))
print("-" * 92)
for iid in ids:
    g = add_lines(ds[iid]["patch"]); n = len(g)
    cells = []
    for run, patch in (("s5-baseline", mini_patch("s5-baseline", iid)),
                       ("s5-baseline-nonet", mini_patch("s5-baseline-nonet", iid)),
                       ("s5-mine", mine_patch(iid))):
        r = res(run, iid)
        rc = (len(g & add_lines(patch)) / n) if (n and patch) else 0.0
        cells.append((r, rc, (patch or "")))
    rows.append((iid, n, cells))
    print("%-30s %5d | %s %.2f%s | %s %.2f%s | %s %.2f" % (
        iid, n,
        "Y" if cells[0][0] else "-", cells[0][1], " E" if cells[0][1] >= 0.999 else "  ",
        "Y" if cells[1][0] else "-", cells[1][1], " E" if cells[1][1] >= 0.999 else "  ",
        "Y" if cells[2][0] else "-", cells[2][1]))

print("\n=== 三档统计（分母一律 25，防⑩⑱ 的分母陷阱）===")
print("%-12s %-9s %-16s %-10s %-12s" % ("组", "resolved", "有patch但unres", "空patch", "逐行=gold"))
for k, label in ((0, "MINI-NET"), (1, "MINI-NONET"), (2, "MINE")):
    r = sum(1 for _, _, c in rows if c[k][0])
    empty = sum(1 for _, _, c in rows if not c[k][2].strip())
    nonres_patch = sum(1 for _, _, c in rows if (not c[k][0]) and c[k][2].strip())
    exact = sum(1 for _, _, c in rows if c[k][1] >= 0.999 and c[k][2].strip())
    print("%-12s %-9s %-16s %-10s %-12s" % (label, "%d/25" % r, nonres_patch, empty, exact))

print("\n=== 按 gold 新增行数分层 ===")
for lo, hi, label in ((0, 2, "<=2 行 (平凡)"), (3, 8, "3-8 行"), (9, 10 ** 9, ">8 行")):
    sel = [(i, n, c) for i, n, c in rows if lo <= n <= hi]
    line = "%-14s n=%-2d |" % (label, len(sel))
    for k, nm in ((0, "MINI-NET"), (1, "MINI-NONET"), (2, "MINE")):
        r = sum(1 for _, _, c in sel if c[k][0])
        ex = sum(1 for _, _, c in sel if c[k][0] and c[k][1] >= 0.999)
        line += " %s res=%-2d 逐行=gold=%-2d |" % (nm, r, ex)
    print(line)
