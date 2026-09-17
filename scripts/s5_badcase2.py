#!/usr/bin/env python3
"""S5 badcase 归因 第二轮：区分「轮数不够」与「从不动手」。

三个判别量：
  A 首次 apply_patch 落在第几步 —— 动手时机的分布（出 patch 组 vs 空 patch 组）
  B 后 10 步里「首次出现的文件」占比 —— 高 = 还在发散，低 = 在收敛
  C 后 10 步里读的是不是待修源码 —— 读 CHANGES/.git/setup.cfg 说明已经不知道该干什么
"""
import json
from pathlib import Path

D = Path.home() / "swe-bench-eval/results/inference/s5-mine"

# 与修 bug 无关的「兜底翻阅」目标
NOISE = (".git", "CHANGES", "ChangeLog", "setup.cfg", "setup.py", "__pkginfo__",
         "AUTHORS", "LICENSE", "README", "MANIFEST", "tox.ini", "doc/whatsnew",
         "CONTRIBUTING", "__init__.py")


def touched(step):
    a = step.get("tool_args") or {}
    p = a.get("path")
    return p if isinstance(p, str) else None


def is_noise(p):
    return p is not None and any(n in p for n in NOISE)


rows = []
for f in sorted(D.glob("*.traj.json")):
    d = json.load(open(f, encoding="utf-8"))
    steps = d["steps"]
    iid = d["instance_id"]

    # A 首次 / 末次 apply_patch
    patches = [s["index"] for s in steps if s["tool_name"] == "apply_patch"]
    first_patch = patches[0] if patches else None

    # B 后 10 步的新文件率（相对前面所有步见过的文件）
    tail = steps[-10:]
    seen = {touched(s) for s in steps[:-10]} - {None}
    tail_paths = [touched(s) for s in tail]
    tail_named = [p for p in tail_paths if p]
    new_in_tail = [p for p in tail_named if p not in seen]

    # C 后 10 步的噪音率
    noise_tail = [p for p in tail_named if is_noise(p)]

    rows.append(dict(
        iid=iid, stop=d["stop_reason"], calls=d["api_calls"],
        plen=len(d["model_patch"]), n_patch=len(patches), first_patch=first_patch,
        tail_n=len(tail_named),
        tail_new=len(new_in_tail), tail_noise=len(noise_tail),
        noise_names=sorted({p for p in noise_tail})[:3],
    ))

G_EMPTY = [r for r in rows if r["plen"] == 0]
G_PATCH = [r for r in rows if r["plen"] > 0]


def pct(a, b):
    return f"{a/b*100:.0f}%" if b else "—"


print("=" * 88)
print("A 动手时机：首次 apply_patch 落在第几步")
print("=" * 88)
print(f"{'instance':<30} {'stop':<10} {'calls':>5} {'patch字符':>8} "
      f"{'apply次数':>8} {'首次在第':>8}")
for r in sorted(rows, key=lambda x: (x["plen"] == 0, x["first_patch"] or 999)):
    fp = r["first_patch"] if r["first_patch"] else "—— 从未"
    print(f"{r['iid']:<30} {r['stop']:<10} {r['calls']:>5} {r['plen']:>8} "
          f"{r['n_patch']:>8} {str(fp):>8}")

fps = [r["first_patch"] for r in G_PATCH if r["first_patch"]]
print()
print(f"出 patch 的 {len(G_PATCH)} 条：{len(fps)} 条用了 apply_patch，"
      f"首次动手步号 min={min(fps)} 中位={sorted(fps)[len(fps)//2]} max={max(fps)}")
print(f"空 patch 的 {len(G_EMPTY)} 条：apply_patch 调用总数 = "
      f"{sum(r['n_patch'] for r in G_EMPTY)}")

print()
print("=" * 88)
print("B/C 末段行为：后 10 步在读什么（空 patch 组）")
print("=" * 88)
print(f"{'instance':<30} {'后10步带路径':>12} {'首次见的新文件':>14} {'非源码兜底':>10}  例子")
for grp, name in ((G_EMPTY, "空 patch"), (G_PATCH, "出 patch")):
    print(f"--- {name} ---")
    for r in sorted(grp, key=lambda x: x["iid"]):
        print(f"{r['iid']:<30} {r['tail_n']:>12} "
              f"{r['tail_new']:>7} {pct(r['tail_new'], r['tail_n']):>6} "
              f"{r['tail_noise']:>4} {pct(r['tail_noise'], r['tail_n']):>5}  "
              f"{','.join(r['noise_names'])}")
    tn = sum(r["tail_n"] for r in grp)
    print(f"{'小计':<30} {tn:>12} {sum(r['tail_new'] for r in grp):>7} "
          f"{pct(sum(r['tail_new'] for r in grp), tn):>6} "
          f"{sum(r['tail_noise'] for r in grp):>4} "
          f"{pct(sum(r['tail_noise'] for r in grp), tn):>5}")
