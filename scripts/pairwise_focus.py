import json, os, re, sys

BASE = "/home/zixu/swe-bench-eval/results/inference"
EDIT_PAT = re.compile(
    r"(sed\s+-i|\bpatch\s+-p|git\s+apply|>\s*[\w./-]+\.(py|txt|rst|cfg)|cat\s*>|tee\s+[\w./-]+\.py"
    r"|open\([^)]*['\"][wa]|write_text|str_replace|<<\s*['\"]?EOF)")
TEST_PAT = re.compile(r"(pytest|runtests\.py|\btox\b|python -m unittest|bin/test)")

def flat(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n] + (" …" if len(s) > n else "")

def show_mine(iid, head_n=8, tail_n=8):
    d = json.load(open("%s/s5-mine/%s.traj.json" % (BASE, iid)))
    steps = d["steps"]
    paths = [ (s.get("tool_args") or {}).get("path") for s in steps if s["tool_name"] == "read_file" ]
    paths = [p for p in paths if p]
    uniq = {}
    for p in paths:
        uniq[p] = uniq.get(p, 0) + 1
    top = sorted(uniq.items(), key=lambda kv: -kv[1])[:4]
    print("  [MINE] read_file %d calls / %d unique files; top: %s"
          % (len(paths), len(uniq), ", ".join("%s x%d" % (p.split("/")[-1], c) for p, c in top)))
    def row(s):
        a = s.get("tool_args") or {}
        if s["tool_name"] == "read_file":
            arg = "%s [%s:%s]" % (a.get("path"), a.get("offset", 0), a.get("limit", "-"))
        elif s["tool_name"] == "search_code":
            arg = "/%s/ %s" % (a.get("pattern"), a.get("path") or a.get("glob") or "")
        else:
            arg = flat(json.dumps(a, ensure_ascii=False), 90)
        th = flat(s.get("thought"), 130)
        out = "  %3s %-11s %s" % (s["index"], s["tool_name"], flat(arg, 95))
        if th:
            out += "\n        \" %s" % th
        return out
    idx = list(range(min(head_n, len(steps)))) + list(range(max(0, len(steps) - tail_n), len(steps)))
    seen = set()
    for i in idx:
        if i in seen:
            continue
        seen.add(i)
        if i == len(steps) - tail_n and head_n < len(steps) - tail_n:
            print("        ... (%d steps omitted) ..." % (len(steps) - tail_n - head_n))
        print(row(steps[i]))

def show_mini(iid, head_n=6, around=2):
    d = json.load(open("%s/s5-baseline/%s/%s.traj.json" % (BASE, iid, iid)))
    turns = []
    cur = None
    for m in d.get("messages", []):
        if m.get("role") == "assistant":
            cur = {"think": m.get("content") or "", "cmds": [], "obs": []}
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                try:
                    a = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    a = {"raw": fn.get("arguments")}
                cur["cmds"].append(a.get("command") or json.dumps(a, ensure_ascii=False))
            turns.append(cur)
        elif m.get("role") in ("tool", "user") and cur is not None:
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            cur["obs"].append(c or "")
    fe = None
    for i, t in enumerate(turns):
        if any(EDIT_PAT.search(c) for c in t["cmds"]):
            fe = i
            break
    def row(i, width=210):
        t = turns[i]
        s = []
        if t["think"]:
            s.append('  T%-3d " %s' % (i + 1, flat(t["think"], 150)))
        for c in t["cmds"]:
            tag = "EDIT" if EDIT_PAT.search(c) else ("TEST" if TEST_PAT.search(c) else "cmd ")
            s.append("  T%-3d %s %s" % (i + 1, tag, flat(c, width)))
        for o in t["obs"][:1]:
            rc = re.search(r"<returncode>(-?\d+)</returncode>", o)
            s.append("        <- rc=%s %s" % (rc.group(1) if rc else "?", flat(re.sub(r"</?\w+>", " ", o), 130)))
        return "\n".join(s)
    print("  [MINI] %d turns, first_edit turn=%s" % (len(turns), fe + 1 if fe is not None else None))
    for i in range(min(head_n, len(turns))):
        print(row(i))
    if fe is not None:
        print("        ... jump to first edit ...")
        for i in range(max(head_n, fe - 1), min(len(turns), fe + around + 1)):
            print(row(i, width=330))

for iid in sys.argv[1:]:
    print("\n" + "=" * 78)
    print("### " + iid)
    print("=" * 78)
    show_mine(iid)
    print()
    show_mini(iid)
