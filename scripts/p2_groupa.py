"""P2 A 组对读（$0）：那 8 条「仍从未动手」的实例，run_python 用了多少次、用来干什么。

A 组定义：apply_patch 调用数 == 0（从未进入编辑阶段）。
「仍从未动手」= S5 的 A 组 ∩ P2 的 A 组（8 条）。
两条对照：django-14631（S5 在 A 组、P2 挪出并 RESOLVED）· sphinx-9711（S5 RESOLVED、P2 掉进 A 组）。

⚠️ 轮号口径：steps 列表是「工具调用」，一轮可含多个工具；step["index"] 才是模型轮数
（`loop.py:476` 在内层 for 里 append，`--max-steps` 限的是 `loop.py:408` 的轮数）。
本脚本一律用 step["index"] 作轮号，需要工具序号时另标 ord=。

用法：
  p2_groupa.py counts  <run-dir> [<run-dir2>]   每实例工具分布 + run_python 次数
  p2_groupa.py dump    <run-dir> <instance_id>  逐条 run_python 的轮号 / 状态 / code 预览
  p2_groupa.py code    <run-dir> <instance_id> <round>  某一轮的 code 全文 + 观察全文
"""
import json
import sys
import collections
import pathlib

# S5 ∩ P2 的 A 组，8 条
STILL = [
    "django__django-10554",
    "django__django-11138",
    "pylint-dev__pylint-4551",
    "pylint-dev__pylint-8898",
    "sphinx-doc__sphinx-11510",
    "sphinx-doc__sphinx-8638",
    "sympy__sympy-17630",
    "sympy__sympy-18211",
]
# 两条对照
CONTRAST = ["django__django-14631", "sphinx-doc__sphinx-9711"]


def load(run: pathlib.Path, iid: str):
    return json.loads((run / f"{iid}.traj.json").read_text())


def steps_of(data):
    """(轮号 index, 工具序号 ord, step)。"""
    for o, st in enumerate(data.get("steps", []), 1):
        yield st.get("index"), o, st


def cmd_counts(argv):
    runs = [pathlib.Path(p) for p in argv]
    ids = STILL + CONTRAST
    for run in runs:
        print(f"=== {run} ===")
        hdr = f"{'instance':38s} {'rounds':>6s} {'tools':>5s} {'rpy':>4s} {'read':>5s} {'srch':>5s} {'tests':>5s} {'apply':>5s} {'diff':>4s}"
        print(hdr)
        for iid in ids:
            f = run / f"{iid}.traj.json"
            if not f.exists():
                continue
            d = json.loads(f.read_text())
            c = collections.Counter(st.get("tool_name") for _, _, st in steps_of(d))
            rounds = len({i for i, _, _ in steps_of(d)})
            print(
                f"{iid:38s} {rounds:6d} {sum(c.values()):5d} {c.get('run_python', 0):4d} "
                f"{c.get('read_file', 0):5d} {c.get('search_code', 0):5d} "
                f"{c.get('run_tests', 0):5d} {c.get('apply_patch', 0):5d} {c.get('git_diff', 0):4d}"
            )
        print()


def cmd_dump(argv):
    run, iid = pathlib.Path(argv[0]), argv[1]
    d = load(run, iid)
    print(f"=== {iid} @ {run} ===")
    print(f"stop={d.get('stop_reason')} api_calls={d.get('api_calls')} patch_len={len(d.get('model_patch') or '')}")
    print()
    for idx, o, st in steps_of(d):
        if st.get("tool_name") != "run_python":
            continue
        code = (st.get("tool_args") or {}).get("code", "")
        oneline = " ⏎ ".join(l.strip() for l in code.splitlines() if l.strip())
        print(f"[轮{idx:3d} ord{o:3d}] {st.get('status')}/{st.get('failure_category')} "
              f"len={len(code):5d} :: {oneline[:260]}")
    print()


def cmd_code(argv):
    run, iid, want = pathlib.Path(argv[0]), argv[1], int(argv[2])
    d = load(run, iid)
    for idx, o, st in steps_of(d):
        if idx != want:
            continue
        print(f"--- 轮{idx} ord{o} tool={st.get('tool_name')} status={st.get('status')}/{st.get('failure_category')}")
        if st.get("thought"):
            print(f"[thought] {st['thought'][:1500]}")
        args = st.get("tool_args") or {}
        for k, v in args.items():
            print(f"[arg {k}]\n{str(v)[:3000]}")
        print(f"[summary]\n{str(st.get('summary'))[:3000]}")
        print()


CMDS = {"counts": cmd_counts, "dump": cmd_dump, "code": cmd_code}


# ---------------- 分类器（【推算】，规则见下；未命中一律进 UNCLASSIFIED 显式打印） ----------------
# 口径：按「这段 code 在干什么」四分类。多标签时按 ARCH > REPRO > BROWSE > TRIVIAL 取首个，
# 因为 ARCH 是本次要量化的新增失败模式，宁可高估它也不要漏（高估方向会被逐条抽查纠正）。
import re

ARCH_PAT = [
    r"\bgit['\"]?\s*,\s*['\"](log|show|branch|tag|reflog|for-each-ref|remote|describe|rev-parse|cat-file|ls-remote)",
    r"git (log|show|branch|tag|reflog|for-each-ref|remote|describe|rev-parse)",
    r"pip['\"]?\s*,\s*['\"]download", r"pip download", r"pip show", r"-m['\"]?\s*,\s*['\"]?pip",
    r"\.cache/pip", r"miniconda3/pkgs", r"conda",
    r"glob\.glob\(\s*['\"]/\*\*", r"os\.walk\(\s*['\"]?/(usr|opt|root|home|tmp)",
    r"\[['\"]find['\"]\s*,\s*['\"]/", r"find / ", r"find /,", r"roots\s*=\s*\[",
    r"other sphinx|different version|OTHER |another install",
]
BROWSE_PAT = [
    r"inspect\.getsource", r"open\(['\"]/?\S+\)\.read\(\)", r"open\(['\"][^'\"]+['\"]\)\.read",
    r"\.read\(\)\.splitlines", r"['\"]grep['\"]", r"grep -rn|grep -rl|grep -n|grep -rln",
    r"enumerate\(open\(", r"open\(['\"][^'\"]+['\"]\)",
    r"\[['\"]cat['\"]",
]
TRIVIAL_PAT = [r"HELLO"]  # 冒烟用的固定串；版本探查改由 _version_probe_only() 整段判（待办②）

# ⚠️ 待办② 修正（2026-09-20，不静默改）。原 TRIVIAL_PAT 第一条是
#     r"^\s*import \w+\s*\n\s*print\(\w+\.(__version__|VERSION|get_version\(\)|__file__)"
# 配 re.M —— 只要**任意位置**出现「import x 换行 print(x.__version__)」就判 TRIVIAL，
# **不看版本行后面还跑了什么**。实测有三轮真复现被它抢走，害得 T 偏晚或不存在
# （docs/EVAL-switch-point.md §4.4 第一条、§七第 2 条；影响面与新旧读数对照见 docs/EVAL-repair-gate-N.md §一）。
# 改法：整段**只有** import 与版本打印才算 TRIVIAL。
# `HELLO` 那条**保持原行为不动** —— 收严它会把 print("HELLO") 这类冒烟代码推进 REPRO 兜底，等于换一个病。
_VER_ATTR = r"(?:__version__|VERSION|get_version\(\)|__file__)"
_PROBE_LINE = re.compile(
    r"^\s*(?:"
    r"#.*"
    r"|import\s+[\w.]+(?:\s+as\s+\w+)?"
    r"|from\s+[\w.]+\s+import\s+[\w.,\s*]+"
    rf"|print\([^()]*{_VER_ATTR}[^()]*\)"
    r")\s*$"
)


def _version_probe_only(code: str) -> bool:
    """整段只有 import 与版本打印 —— 什么都没跑，才算 TRIVIAL（待办②）。"""
    lines = [ln for ln in code.splitlines() if ln.strip()]
    return bool(lines) and all(_PROBE_LINE.match(ln) for ln in lines)


def classify(code: str) -> str:
    c = code
    if _version_probe_only(c):
        return "TRIVIAL"
    for p in TRIVIAL_PAT:
        if re.search(p, c, re.M):
            return "TRIVIAL"
    for p in ARCH_PAT:
        if re.search(p, c):
            return "ARCH"
    for p in BROWSE_PAT:
        if re.search(p, c):
            return "BROWSE"
    # 剩下的：在跑被测代码本身（import 项目包 / 构造对象 / 建临时工程）
    if re.search(r"^\s*(import|from)\s+\w+", c, re.M):
        return "REPRO"
    return "UNCLASSIFIED"


def cmd_classify(argv):
    run = pathlib.Path(argv[0])
    ids = argv[1:] if len(argv) > 1 else STILL + CONTRAST
    tot = collections.Counter()
    print(f"{'instance':38s} {'rpy':>4s} {'REPRO':>6s} {'BROWSE':>7s} {'ARCH':>5s} {'TRIV':>5s} {'??':>3s}  首个ARCH轮")
    for iid in ids:
        f = run / f"{iid}.traj.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        c = collections.Counter()
        first_arch = None
        for idx, o, st in steps_of(d):
            if st.get("tool_name") != "run_python":
                continue
            k = classify((st.get("tool_args") or {}).get("code", ""))
            c[k] += 1
            tot[k] += 1
            if k == "ARCH" and first_arch is None:
                first_arch = idx
        n = sum(c.values())
        print(f"{iid:38s} {n:4d} {c['REPRO']:6d} {c['BROWSE']:7d} {c['ARCH']:5d} "
              f"{c['TRIVIAL']:5d} {c['UNCLASSIFIED']:3d}  {first_arch if first_arch else '-'}")
    print(f"\n合计 {dict(tot)}")
    print("\n--- UNCLASSIFIED 全文（不许静默归桶）---")
    for iid in ids:
        f = run / f"{iid}.traj.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        for idx, o, st in steps_of(d):
            if st.get("tool_name") != "run_python":
                continue
            code = (st.get("tool_args") or {}).get("code", "")
            if classify(code) == "UNCLASSIFIED":
                print(f"[{iid} 轮{idx}] {code[:300]}")


def cmd_order(argv):
    """全 25 条：首次 run_tests / 首次 apply_patch / 首次任何动态证据（run_python|run_tests）的轮号。"""
    run = pathlib.Path(argv[0])
    rows = []
    for tf in sorted(run.glob("*.traj.json")):
        d = json.loads(tf.read_text())
        firsts = {}
        for idx, o, st in steps_of(d):
            firsts.setdefault(st.get("tool_name"), idx)
        rows.append((d["instance_id"], firsts, len(d.get("model_patch") or "")))
    print(f"{'instance':38s} {'1stRPY':>7s} {'1stTEST':>8s} {'1stAPPLY':>9s} {'patch':>6s}")
    for iid, f, pl in rows:
        g = lambda k: f.get(k, 0) or "-"
        print(f"{iid:38s} {str(g('run_python')):>7s} {str(g('run_tests')):>8s} "
              f"{str(g('apply_patch')):>9s} {pl:6d}")


CMDS["classify"] = cmd_classify
CMDS["order"] = cmd_order



def cmd_confound(argv):
    """替代解释「A 组就是难题」的免费排除：A/B 组 × gold 规模 × 三个对照组的 resolved。
    分层沿用 EVAL-S5-pairwise.md：gold 新增行 ≤2 为平凡层。需要 .venv/bin/python（datasets）。"""
    from datasets import load_dataset
    run = pathlib.Path("results/inference/p2-mine")
    ds = {r["instance_id"]: r for r in load_dataset("SWE-bench/SWE-bench_Verified", split="test")}

    def resolved(run_id):
        p = pathlib.Path(f"logs/evaluation/{run_id}/results.json")
        return set(json.loads(p.read_text())["resolved_ids"])

    r_p2, r_s5 = resolved("p2-mine"), resolved("s5-mine")
    r_bnet, r_bnon = resolved("s5-baseline"), resolved("s5-baseline-nonet")

    rows = []
    for tf in sorted(run.glob("*.traj.json")):
        d = json.loads(tf.read_text())
        iid = d["instance_id"]
        c = collections.Counter()
        cls = collections.Counter()
        for _, _, st in steps_of(d):
            c[st.get("tool_name")] += 1
            if st.get("tool_name") == "run_python":
                cls[classify((st.get("tool_args") or {}).get("code", ""))] += 1
        goldadd = sum(1 for l in ds[iid]["patch"].splitlines()
                      if l.startswith("+") and not l.startswith("+++"))
        rows.append((iid, "A" if c["apply_patch"] == 0 else "B", goldadd,
                     iid in r_p2, iid in r_s5, iid in r_bnon, iid in r_bnet,
                     c["run_python"], cls["ARCH"], cls["REPRO"]))

    print(f"{'instance':32s} 组 {'gold+':>5s} {'层':>4s} {'P2':>3s} {'S5':>3s} {'mini无网':>7s} {'mini有网':>7s} {'rpy':>4s} {'ARCH':>5s} {'REPRO':>6s}")
    y = lambda b: "✓" if b else "·"
    for r in sorted(rows, key=lambda r: (r[1], -r[2])):
        layer = "平凡" if r[2] <= 2 else "非平凡"
        print(f"{r[0]:32s} {r[1]:s} {r[2]:5d} {layer:>4s} {y(r[3]):>3s} {y(r[4]):>3s} "
              f"{y(r[5]):>7s} {y(r[6]):>7s} {r[7]:4d} {r[8]:5d} {r[9]:6d}")

    for g in "AB":
        sub = [r for r in rows if r[1] == g]
        n = len(sub)
        gs = sorted(r[2] for r in sub)
        med = gs[n // 2] if n % 2 else (gs[n // 2 - 1] + gs[n // 2]) / 2
        print(f"\n{g} 组 n={n}  gold+ 中位={med} 均值={sum(gs)/n:.1f} 区间=[{gs[0]},{gs[-1]}]"
              f"  非平凡 {sum(1 for r in sub if r[2] > 2)}/{n}"
              f"  mini无网过 {sum(1 for r in sub if r[5])}/{n}"
              f"  mini有网过 {sum(1 for r in sub if r[6])}/{n}"
              f"  S5过 {sum(1 for r in sub if r[4])}/{n}")


CMDS["confound"] = cmd_confound



NET_PAT = r"pip['\"]?\s*,?\s*['\"]?\s*(download|install)|pip (download|install)|urllib|requests\.|urlopen|\bcurl\b|\bwget\b|socket\.|https?://|git['\"]?\s*,\s*['\"](clone|fetch|pull|ls-remote)|git (clone|fetch|pull|ls-remote)"
# 上游 PR/issue 号的「找现成答案」指纹：全盘/缓存里 grep 一串数字，或 grep gold patch 的字面串
HUNT_PAT = r"grep -r\w* ['\"]?\d{4,5}|mentioning \d{4,5}|\.patch|\.diff['\"]|--include=.*patch"


def cmd_net(argv):
    """真实跑里模型有没有去摸网 / 找上游答案，以及观察返回了什么。"""
    run = pathlib.Path(argv[0])
    nhit = collections.Counter()
    for tf in sorted(run.glob("*.traj.json")):
        d = json.loads(tf.read_text())
        for idx, o, st in steps_of(d):
            if st.get("tool_name") != "run_python":
                continue
            code = (st.get("tool_args") or {}).get("code", "")
            tags = []
            if re.search(NET_PAT, code):
                tags.append("NET")
            if re.search(HUNT_PAT, code):
                tags.append("HUNT")
            if not tags:
                continue
            nhit["+".join(tags)] += 1
            nhit["_inst_" + d["instance_id"]] += 1
            summ = " ".join(str(st.get("summary") or "").split())
            print(f"[{d['instance_id']} 轮{idx}] {'+'.join(tags)} {st.get('status')}")
            print(f"   code: {' ⏎ '.join(l.strip() for l in code.splitlines() if l.strip())[:220]}")
            print(f"   obs : {summ[:300]}")
    insts = sorted(k[6:] for k in nhit if k.startswith("_inst_"))
    agg = {k: v for k, v in nhit.items() if not k.startswith("_inst_")}
    print()
    print(f"合计 {agg}")
    print(f"涉及 {len(insts)} 个实例：{insts}")


CMDS["net"] = cmd_net



def cmd_profile(argv):
    """每实例：首次 REPRO 轮号 · 末 10 轮（轮31-40）的 run_python 构成 · 四类占比。"""
    run = pathlib.Path(argv[0])
    rows = []
    for tf in sorted(run.glob("*.traj.json")):
        d = json.loads(tf.read_text())
        c = collections.Counter()
        cls = collections.Counter()
        tail = collections.Counter()
        first = {}
        for idx, o, st in steps_of(d):
            c[st.get("tool_name")] += 1
            if st.get("tool_name") != "run_python":
                continue
            k = classify((st.get("tool_args") or {}).get("code", ""))
            cls[k] += 1
            first.setdefault(k, idx)
            if idx >= 31:
                tail[k] += 1
        rows.append((d["instance_id"], "A" if c["apply_patch"] == 0 else "B", cls, first, tail, c))

    print(f"{'instance':32s} 组 {'1stREPRO':>8s} {'1stARCH':>7s} {'REPRO%':>7s} "
          f"{'末10轮 rpy':>10s} {'其中非诊断':>10s}")
    for iid, g, cls, first, tail, c in sorted(rows, key=lambda r: r[1]):
        n = sum(cls.values())
        rp = f"{cls['REPRO']/n*100:.0f}%" if n else "-"
        nt = sum(tail.values())
        bad = tail["ARCH"] + tail["BROWSE"]
        print(f"{iid:32s} {g} {str(first.get('REPRO', '-')):>8s} {str(first.get('ARCH', '-')):>7s} "
              f"{rp:>7s} {nt:>10d} {str(bad) + '/' + str(nt) if nt else '-':>10s}")

    for g in "AB":
        sub = [r for r in rows if r[1] == g]
        tot = collections.Counter()
        tailtot = collections.Counter()
        for _, _, cls, _, tail, _ in sub:
            tot.update(cls)
            tailtot.update(tail)
        n = sum(tot.values())
        fr = [r[3]["REPRO"] for r in sub if "REPRO" in r[3]]
        print(f"\n{g} 组 n={len(sub)}  run_python {n} 次  "
              f"REPRO {tot['REPRO']}({tot['REPRO']/n*100:.0f}%) "
              f"ARCH {tot['ARCH']}({tot['ARCH']/n*100:.0f}%) "
              f"BROWSE {tot['BROWSE']}({tot['BROWSE']/n*100:.0f}%) TRIV {tot['TRIVIAL']}")
        print(f"   有 REPRO 的 {len(fr)}/{len(sub)}，首次 REPRO 轮号中位 "
              f"{sorted(fr)[len(fr)//2] if fr else '-'}  区间 [{min(fr) if fr else '-'},{max(fr) if fr else '-'}]")
        nt = sum(tailtot.values())
        print(f"   末 10 轮 run_python {nt} 次，其中 ARCH+BROWSE {tailtot['ARCH']+tailtot['BROWSE']}"
              f"({(tailtot['ARCH']+tailtot['BROWSE'])/nt*100:.0f}%)" if nt else "   末 10 轮无 run_python")


CMDS["profile"] = cmd_profile

if __name__ == "__main__":
    CMDS[sys.argv[1]](sys.argv[2:])
