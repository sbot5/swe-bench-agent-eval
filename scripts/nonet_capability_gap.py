import json, os, re, collections
# P1 结论边界：断网消掉的只是「联网取件」一个差异，mini 的 shell 还在。
# 把「断网后 mini 仍能做而我方做不到的事」量出来，别只口头声明（㉑ 的第三形态）。2026-09-17。
INF = "/home/zixu/swe-bench-eval/results/inference"

CAP = [  # 按「我方六工具能不能做到」分类
    ("跑复现脚本",  re.compile(r"(python[0-9.]*\s+(-c\b|/tmp/|\S*\.py)|python[0-9.]*\s*<<)"), "我方无"),
    ("跑测试",      re.compile(r"(pytest|runtests\.py|tox\b|python -m unittest|\./tests/)"),   "我方有 run_tests"),
    ("流式编辑",    re.compile(r"(sed -i|\bawk\b|>>\s*\S+\.py|cat\s*>\s*\S+\.py|tee\b)"),      "我方无(只有 apply_patch)"),
    ("读文件",      re.compile(r"(\bcat\b|\bhead\b|\btail\b|sed -n|\bless\b|\bnl\b)"),         "我方有 read_file"),
    ("搜代码",      re.compile(r"(\bgrep\b|\brg\b|\bfind\b|\bls\b)"),                          "我方有 search_code"),
    ("git 操作",    re.compile(r"\bgit\s+(diff|status|log|stash|checkout|apply)"),             "我方有 git_diff"),
    ("装包",        re.compile(r"(pip install|pip download|conda install|apt-get)"),           "我方无(断网后也废)"),
]

def scan(run):
    base = "%s/%s" % (INF, run)
    ids = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    if not ids:
        ids = sorted(f[:-len(".traj.json")] for f in os.listdir(base) if f.endswith(".traj.json"))
    cnt = collections.Counter(); inst = collections.defaultdict(set); ncmd = 0
    for iid in ids:
        p = "%s/%s/%s.traj.json" % (base, iid, iid)
        if not os.path.exists(p): p = "%s/%s.traj.json" % (base, iid)
        if not os.path.exists(p): continue
        for m in json.load(open(p)).get("messages", []):
            if m.get("role") != "assistant": continue
            for tc in (m.get("tool_calls") or []):
                try: c = json.loads((tc.get("function") or {}).get("arguments") or "{}").get("command") or ""
                except Exception: c = ""
                if not c: continue
                ncmd += 1
                for name, rx, _ in CAP:
                    if rx.search(c): cnt[name] += 1; inst[name].add(iid)
    print("\n##### %s —— %d 条实例，%d 条 shell 命令" % (run, len(ids), ncmd))
    print("%-12s %8s %8s   %s" % ("能力", "调用数", "覆盖实例", "我方对应"))
    for name, _, mine in CAP:
        print("%-12s %8d %8d   %s" % (name, cnt[name], len(inst[name]), mine))
    return len(ids)

def mine_tools():
    base = "%s/s5-mine" % INF
    cnt = collections.Counter(); inst = collections.defaultdict(set)
    for f in sorted(os.listdir(base)):
        if not f.endswith(".traj.json"): continue
        iid = f[:-len(".traj.json")]
        d = json.load(open(os.path.join(base, f)))
        for s in d.get("steps", []) or []:
            t = s.get("tool_name") or s.get("tool") or s.get("name")
            if t: cnt[t] += 1; inst[t].add(iid)
    print("\n##### s5-mine（我方六工具）")
    if not cnt:
        print("  (steps 结构与预期不符，跳过；口径见 CLAUDE.md 的 `steps` 那条)")
    for t, n in cnt.most_common():
        print("%-14s %8d %8d" % (t, n, len(inst[t])))

for r in ("s5-baseline", "s5-baseline-nonet"):
    if os.path.isdir("%s/%s" % (INF, r)): scan(r)
mine_tools()
