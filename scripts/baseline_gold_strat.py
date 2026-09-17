import json, os, re
ROOT="/home/zixu/swe-bench-eval"; INF=ROOT+"/results/inference"; EV=ROOT+"/results/evaluation"
os.environ["HF_DATASETS_OFFLINE"]="1"
from datasets import load_dataset
ds={r["instance_id"]:r for r in load_dataset("SWE-bench/SWE-bench_Verified",split="test")}
R1=re.compile(r"(\.patch\b|\.diff\b|/pulls/\d+/files)")
R2=re.compile(r"(raw\.githubusercontent\.com|pip download|git clone https)")
R3=re.compile(r"api\.github\.com/(search|repos)/")

def add_lines(p):
    return {re.sub(r"\s+"," ",l[1:]).strip() for l in (p or "").splitlines()
            if l.startswith("+") and not l.startswith("+++") and l[1:].strip()}

def res(run,iid):
    p="%s/%s/%s.report.json"%(EV,run,iid)
    if not os.path.exists(p): return False
    d=json.load(open(p)); return bool((d.get(iid) or d).get("resolved"))

ids=sorted(i for i in ds if os.path.exists("%s/s5-mine/%s.traj.json"%(INF,i)))
print("%-30s %5s %4s %4s | %-9s | %-9s" % ("instance","gold+","mR","nR","MINI","MINE"))
print("-"*78)
buckets={"triv":[], "mid":[], "big":[]}
for iid in ids:
    g=add_lines(ds[iid]["patch"]); n=len(g)
    b=json.load(open("%s/s5-baseline/%s/%s.traj.json"%(INF,iid,iid)))
    mp=(b.get("info") or {}).get("submission") or ""
    np_=json.load(open("%s/s5-mine/%s.traj.json"%(INF,iid)))["model_patch"] or ""
    cats=set()
    for m in b.get("messages",[]):
        if m.get("role")!="assistant": continue
        for tc in (m.get("tool_calls") or []):
            try: c=json.loads((tc.get("function") or {}).get("arguments") or "{}").get("command") or ""
            except Exception: c=""
            if R1.search(c): cats.add("R1")
            elif R2.search(c): cats.add("R2")
            elif R3.search(c): cats.add("R3")
    mr=len(g&add_lines(mp))/n if n else 0
    nr=len(g&add_lines(np_))/n if n else 0
    bk="triv" if n<=2 else ("mid" if n<=8 else "big")
    buckets[bk].append((res("s5-baseline",iid),mr,res("s5-mine",iid),nr))
    print("%-30s %5d %4s %4s | %.2f %-4s | %.2f %s"
          % (iid,n,"Y" if res("s5-baseline",iid) else "-","Y" if res("s5-mine",iid) else "-",
             mr,"".join(sorted(cats)) or "-",nr,""))
print("\n=== 按 gold 新增行数分层（只统计该侧 resolved 的条目）===")
for k,label in (("triv","<=2 行 (平凡)"),("mid","3-8 行"),("big",">8 行")):
    rows=buckets[k]
    mi=[r[1] for r in rows if r[0]]; mn=[r[3] for r in rows if r[2]]
    print("%-14s n=%-2d | MINI resolved=%-2d exact(=1.00)=%-2d | MINE resolved=%-2d exact(=1.00)=%-2d  mean=%.2f"
          % (label,len(rows),len(mi),sum(1 for x in mi if x>=0.999),len(mn),sum(1 for x in mn if x>=0.999),
             (sum(mn)/len(mn)) if mn else 0))
