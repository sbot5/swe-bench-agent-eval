import json, os, re

BASE = "/home/zixu/swe-bench-eval/results/inference"
OUT = "/home/zixu/pairwise"
os.makedirs(OUT, exist_ok=True)

GROUPS = {
    "A": ["django__django-11138", "django__django-14631", "pylint-dev__pylint-8898",
          "sphinx-doc__sphinx-8638", "sympy__sympy-17630", "sympy__sympy-18211"],
    "B": ["astropy__astropy-14182", "django__django-12039", "django__django-13512"],
}

EDIT_PAT = re.compile(
    r"(sed\s+-i|\bpatch\s+-p|git\s+apply|>\s*[\w./-]+\.(py|txt|rst|cfg)|cat\s*>|tee\s+[\w./-]+\.py"
    r"|open\([^)]*['\"][wa]|write_text|str_replace|<<\s*['\"]?EOF)")
TEST_PAT = re.compile(r"(pytest|runtests\.py|\btox\b|python -m unittest|bin/test)")

def flat(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n] + (" …" if len(s) > n else "")

def mine(iid):
    d = json.load(open("%s/s5-mine/%s.traj.json" % (BASE, iid)))
    lines, hist, first_edit, first_test = [], {}, None, None
    for s in d["steps"]:
        t = s["tool_name"]
        hist[t] = hist.get(t, 0) + 1
        if t == "apply_patch" and first_edit is None:
            first_edit = s["index"]
        if t == "run_tests" and first_test is None:
            first_test = s["index"]
        args = flat(json.dumps(s.get("tool_args") or {}, ensure_ascii=False), 110)
        st = s.get("status")
        mark = "" if st == "ok" else "  [!%s/%s]" % (st, s.get("failure_category") or "-")
        lines.append("%3s %-12s %s%s\n      -> %s" % (
            s["index"], t, args, mark, flat(s.get("summary"), 95)))
    head = {"stop_reason": d.get("stop_reason"), "api_calls": d.get("api_calls"),
            "steps": len(d["steps"]), "patch_chars": len(d.get("model_patch") or ""),
            "duration": round(d.get("total_duration") or 0, 1),
            "first_edit": first_edit, "first_test": first_test, "hist": hist}
    return head, lines

def mini(iid):
    d = json.load(open("%s/s5-baseline/%s/%s.traj.json" % (BASE, iid, iid)))
    info = d.get("info", {})
    lines, first_edit, first_test, turn, ncmd = [], None, None, 0, 0
    pending = []
    for m in d.get("messages", []):
        role = m.get("role")
        if role == "assistant":
            turn += 1
            think = flat(m.get("content") or "", 90)
            if think:
                lines.append("T%-3d [think] %s" % (turn, think))
            pending = []
            for tc in (m.get("tool_calls") or []):
                fn = (tc.get("function") or {})
                try:
                    a = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    a = {"raw": fn.get("arguments")}
                cmd = a.get("command") or json.dumps(a, ensure_ascii=False)
                ncmd += 1
                if EDIT_PAT.search(cmd) and first_edit is None:
                    first_edit = (turn, ncmd)
                if TEST_PAT.search(cmd) and first_test is None:
                    first_test = (turn, ncmd)
                tag = "EDIT" if EDIT_PAT.search(cmd) else ("TEST" if TEST_PAT.search(cmd) else fn.get("name") or "?")
                lines.append("T%-3d c%-3d %-5s %s" % (turn, ncmd, tag, flat(cmd, 165)))
                pending.append(ncmd)
        elif role in ("tool", "user"):
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            c = c or ""
            rc = re.search(r"<returncode>(-?\d+)</returncode>", c)
            out = re.sub(r"</?(returncode|output)>", " ", c)
            lines.append("        <- rc=%s | %s" % (rc.group(1) if rc else "?", flat(out, 110)))
    head = {"exit_status": info.get("exit_status"), "turns": turn, "cmds": ncmd,
            "patch_chars": len(info.get("submission") or ""),
            "model_stats": info.get("model_stats"),
            "first_edit": first_edit, "first_test": first_test}
    return head, lines

ov = ["# 配对轨迹对读 —— 总览\n"]
for g, ids in GROUPS.items():
    ov.append("\n## %s 组\n" % g)
    for iid in ids:
        mh, ml = mine(iid)
        nh, nl = mini(iid)
        ov.append("### %s" % iid)
        ov.append("- MINE: stop=%s api_calls=%s steps=%s patch=%sB dur=%ss first_edit=%s first_test=%s"
                  % (mh["stop_reason"], mh["api_calls"], mh["steps"], mh["patch_chars"],
                     mh["duration"], mh["first_edit"], mh["first_test"]))
        ov.append("  hist=%s" % json.dumps(mh["hist"], sort_keys=True))
        ov.append("- MINI: exit=%s turns=%s cmds=%s patch=%sB first_edit(turn,cmd)=%s first_test=%s"
                  % (nh["exit_status"], nh["turns"], nh["cmds"], nh["patch_chars"],
                     nh["first_edit"], nh["first_test"]))
        with open("%s/%s.md" % (OUT, iid), "w") as f:
            f.write("# %s\n\n## MINE  %s\n\n" % (iid, json.dumps(mh, sort_keys=True)))
            f.write("\n".join(ml))
            f.write("\n\n## MINI  %s\n\n" % json.dumps(nh, sort_keys=True))
            f.write("\n".join(nl))
            f.write("\n")
with open("%s/_overview.md" % OUT, "w") as f:
    f.write("\n".join(ov) + "\n")
print("\n".join(ov))
print("\n--- sizes ---")
for fn in sorted(os.listdir(OUT)):
    print("%8d  %s" % (os.path.getsize(os.path.join(OUT, fn)), fn))
