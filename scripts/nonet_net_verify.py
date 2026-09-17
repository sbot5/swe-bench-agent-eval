import json, os, re, sys
# P1 断网核验：判据不是「0 条联网尝试」（断网不阻止模型尝试），而是「0 条成功取件」。
# 同一把尺同时量有网组与断网组，可疑的一律打印出来人工看。2026-09-17。
INF = "/home/zixu/swe-bench-eval/results/inference"
NET = re.compile(r"(urllib|requests\.|urlopen|\bcurl\b|\bwget\b|github\.com|pip install|pip download|"
                 r"https?://|git fetch|git ls-remote|git clone|git pull)")
FETCH = re.compile(r"(\.patch\b|\.diff\b|/pulls/\d+/files|raw\.githubusercontent)")
FAIL = re.compile(r"(Could not resolve host|Failed to establish|Network is unreachable|"
                  r"Temporary failure in name resolution|No matching distribution|unable to access|"
                  r"Connection refused|Name or service not known|NewConnectionError|"
                  r"Could not find a version|curl: \(6\)|curl: \(7\)|curl: \(28\)|no address associated)", re.I)

def flat(s, n):
    if isinstance(s, list): s = " ".join(str(x) for x in s)
    return re.sub(r"\s+", " ", s or "").strip()[:n]

def scan(run):
    base = "%s/%s" % (INF, run)
    # 两种布局：mini 新版 <iid>/<iid>.traj.json；S2 那会儿是扁平 <iid>.traj.json
    ids = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    if not ids:
        ids = sorted(f[:-len(".traj.json")] for f in os.listdir(base) if f.endswith(".traj.json"))
    inst_attempt = attempts = ok = fetch_ok = 0
    suspicious = []
    for iid in ids:
        p = "%s/%s/%s.traj.json" % (base, iid, iid)
        if not os.path.exists(p):
            p = "%s/%s.traj.json" % (base, iid)
        if not os.path.exists(p): continue
        msgs = json.load(open(p)).get("messages", [])
        hit = False
        for i, m in enumerate(msgs):
            if m.get("role") != "assistant": continue
            for tc in (m.get("tool_calls") or []):
                try: c = json.loads((tc.get("function") or {}).get("arguments") or "{}").get("command") or ""
                except Exception: c = ""
                if not NET.search(c): continue
                hit = True; attempts += 1
                obs = ""
                for nx in msgs[i + 1:i + 3]:
                    if nx.get("role") in ("user", "tool"):
                        obs = nx.get("content") or ""; break
                obs = flat(obs, 4000)
                if not FAIL.search(obs):
                    ok += 1
                    if FETCH.search(c): fetch_ok += 1
                    suspicious.append((iid, flat(c, 130), flat(obs, 170)))
        inst_attempt += 1 if hit else 0
    print("\n########## %s  (%d instances) ##########" % (run, len(ids)))
    print("尝试联网的实例: %d/%d | 联网命令总数: %d | 未见失败特征(=疑似成功): %d | 其中取件类: %d"
          % (inst_attempt, len(ids), attempts, ok, fetch_ok))
    for iid, c, o in suspicious[:25]:
        print("  ? %-28s CMD %s\n      OBS %s" % (iid, c, o))
    if len(suspicious) > 25:
        print("  ... 另有 %d 条" % (len(suspicious) - 25))

for run in (sys.argv[1:] or ["s5-baseline", "s5-baseline-nonet"]):
    if os.path.isdir("%s/%s" % (INF, run)): scan(run)
    else: print("SKIP (不存在):", run)
