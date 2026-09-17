import json, os, re
INF = "/home/zixu/swe-bench-eval/results/inference"
A = ["django__django-11138","django__django-14631","pylint-dev__pylint-8898",
     "sphinx-doc__sphinx-8638","sympy__sympy-17630","sympy__sympy-18211"]
B = ["astropy__astropy-14182","django__django-12039","django__django-13512"]

R1 = re.compile(r"(\.patch\b|\.diff\b|/pulls/\d+/files)")
R2 = re.compile(r"(raw\.githubusercontent\.com|pip download|git clone https)")
R3 = re.compile(r"(api\.github\.com/(search|repos)/[^ ]*(issues|timeline|commits\?))")
EXEC = re.compile(r"python\s*-\s*<<|python\s+-c|python3?\s+-\s*<<")
REPO_EDIT = re.compile(r"(sed\s+-i\s+[^/]|git\s+apply|Path\('(?!/tmp)|Path\(\"(?!/tmp)|open\('(?!/tmp)[^']*',\s*'w|p\.write_text|>\s*(?!/tmp)[\w./-]+\.(py|rst|txt))")
TEST = re.compile(r"(pytest|runtests\.py|\btox\b|python -m unittest|bin/test)")

def flat(s, n):
    return (re.sub(r"\s+", " ", s or "").strip()[:n])

def mini_digest(iid):
    d = json.load(open("%s/s5-baseline/%s/%s.traj.json" % (INF, iid, iid)))
    ev = {"exec": None, "edit": None, "test": None, "r1": [], "r2": [], "r3": []}
    turn = 0
    first_edit_cmd = ""
    for m in d.get("messages", []):
        if m.get("role") != "assistant":
            continue
        turn += 1
        for tc in (m.get("tool_calls") or []):
            try:
                c = json.loads((tc.get("function") or {}).get("arguments") or "{}").get("command") or ""
            except Exception:
                c = ""
            if EXEC.search(c) and not REPO_EDIT.search(c) and ev["exec"] is None:
                ev["exec"] = turn
            if REPO_EDIT.search(c) and ev["edit"] is None:
                ev["edit"] = turn; first_edit_cmd = flat(c, 150)
            if TEST.search(c) and ev["test"] is None:
                ev["test"] = turn
            if R1.search(c): ev["r1"].append(turn)
            elif R2.search(c): ev["r2"].append(turn)
            elif R3.search(c): ev["r3"].append(turn)
    ev["turns"] = turn
    ev["first_edit_cmd"] = first_edit_cmd
    return ev

def mine_digest(iid):
    d = json.load(open("%s/s5-mine/%s.traj.json" % (INF, iid)))
    steps = d["steps"]
    th = [(s["index"], flat(s.get("thought"), 120)) for s in steps if (s.get("thought") or "").strip()]
    return {"api_calls": d.get("api_calls"), "steps": len(steps), "n_thoughts": len(th),
            "first_thoughts": th[:2], "last_thoughts": th[-3:], "patch": len(d.get("model_patch") or "")}

for grp, ids in (("A", A), ("B", B)):
    for iid in ids:
        m, n = mine_digest(iid), mini_digest(iid)
        print("\n#### [%s] %s" % (grp, iid))
        print("  MINI turns=%d | first exec-code turn=%s | first REPO edit turn=%s | first test turn=%s"
              % (n["turns"], n["exec"], n["edit"], n["test"]))
        print("       fetch: R1(patch/diff)=%s  R2(fixed-src)=%s  R3(issue-talk)=%s"
              % (n["r1"] or "-", n["r2"] or "-", n["r3"] or "-"))
        print("       first edit cmd: %s" % n["first_edit_cmd"])
        print("  MINE api_calls=%d steps=%d patch=%dB | thoughts=%d" % (m["api_calls"], m["steps"], m["patch"], m["n_thoughts"]))
        for i, t in m["first_thoughts"]:
            print("       first #%s \" %s" % (i, t))
        for i, t in m["last_thoughts"]:
            print("       last  #%s \" %s" % (i, t))
