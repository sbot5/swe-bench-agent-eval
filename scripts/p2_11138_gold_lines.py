#!/usr/bin/env python3
"""p2_11138_gold_lines.py —— gold patch 的 hunk 落在哪几行，P2 那一跑的 read_file 行段盖住了没有。

接 p2_11138.py 的 window：轮 15 那一刻四个 gold 文件确实都在窗口里（否掉了「窗口装不下」），
但「文件在窗口里」≠「要改的那几行在窗口里」。这一步用 gold patch 的 @@ 行号把它坐实。

需要 datasets（读 HF 本地缓存，$0、不发模型调用）：
    PYTHONPATH=. .venv/bin/python scripts/p2_11138_gold_lines.py
"""
import collections
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
IID = "django__django-11138"


def row():
    from datasets import load_dataset
    ds = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
    for r in ds:
        if r["instance_id"] == IID:
            return r
    raise SystemExit("实例不在 SWE-bench Verified test split 里")


def gold_patch():
    r = row()
    print("=== problem_statement（前 900 字符，【原文·数据集】）===")
    print(r["problem_statement"][:900].strip())
    # 11.6 限制 4：例子全是 MySQL，但标题点名了三个后端 —— 只看前 900 字符会把「例子」读成「通篇」
    ps = r["problem_statement"]
    print(f"\n全文 {len(ps)} 字符；后端名出现次数（不分大小写）："
          + " · ".join(f"{k} {len(re.findall(k, ps, flags=re.I))}" for k in ("mysql", "sqlite", "oracle")))
    for line in ps.splitlines():
        if re.search(r"sqlite|oracle", line, flags=re.I):
            print("  提到 sqlite/oracle 的行 |", line.strip()[:220])
    print("\n=== FAIL_TO_PASS ===")
    print(r["FAIL_TO_PASS"])
    print()
    return r["patch"]


def hunks(patch):
    """(file, old_start, old_len) —— 只取 --- / +++ 与 @@ 头，不解析正文。"""
    out = []
    cur = None
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
        elif line.startswith("@@") and cur:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+", line)
            if m:
                out.append((cur, int(m.group(1)), int(m.group(2) or 1)))
    return out


def main():
    hs = hunks(gold_patch())
    print(f"gold patch：{len(hs)} 个 hunk\n")
    reads = collections.defaultdict(list)
    d = json.loads((ROOT / "results" / "inference" / "p2-mine" / (IID + ".traj.json")).read_text(encoding="utf-8"))
    for s in d["steps"]:
        if s["tool_name"] != "read_file":
            continue
        m = re.match(r"Lines (\d+)-(\d+) of ", s.get("summary") or "")
        if m:
            reads[(s.get("tool_args") or {}).get("path")].append((s["index"], int(m.group(1)), int(m.group(2))))

    print(f"{'file':44s} {'hunk 行':>14s}  盖住它的 read_file（轮:起-止）")
    covered = 0
    for f, start, ln in hs:
        end = start + ln - 1
        hit = [f"{r}:{a}-{b}" for r, a, b in reads.get(f, []) if a <= start and b >= end]
        part = [f"{r}:{a}-{b}" for r, a, b in reads.get(f, []) if not (b < start or a > end)]
        covered += bool(hit)
        print(f"{f:44s} {f'{start}-{end}':>14s}  全覆盖 {hit or '—'}   有重叠 {part or '—'}")
    print(f"\n{len(hs)} 个 hunk 里，被某一次 read_file **完整**读到的有 {covered} 个")

    # 细到 hunk：C8 的 5 条窗口里，任一时刻最多同时留着几个 hunk 的全文
    keep_full = 5
    steps = d["steps"]
    best = (0, None, [])
    for i in range(len(steps)):
        win = steps[max(0, i - keep_full + 1):i + 1]
        live = []
        for w in win:
            if w["tool_name"] != "read_file":
                continue
            m = re.match(r"Lines (\d+)-(\d+) of ", w.get("summary") or "")
            if not m:
                continue
            a, b = int(m.group(1)), int(m.group(2))
            p = (w.get("tool_args") or {}).get("path")
            for f, start, ln in hs:
                if f == p and a <= start and b >= start + ln - 1:
                    live.append(f"{f.split('/')[-1]}:{start}")
        live = sorted(set(live))
        if len(live) > best[0]:
            best = (len(live), steps[i]["index"], live)
    print(f"\nC8 窗口（keep_full={keep_full}）内**同时**留着全文的 gold hunk，峰值 {best[0]}/{len(hs)}，"
          f"出现在轮 {best[1]}：{best[2]}")




def test_patch_check():
    """graded 的那条测试在 base commit 的仓库里存在吗？（SWE-bench 的 test_patch 在评测时才打上）"""
    r = row()
    tp = r["test_patch"]
    name = "test_query_convert_timezones"
    added = [ln for ln in tp.splitlines() if ln.startswith("+") and name in ln]
    print(f"\n=== test_patch 里是否**新增**了 {name} ===")
    print(f"test_patch 触及的文件：{[ln[6:] for ln in tp.splitlines() if ln.startswith('+++ b/')]}")
    for ln in added:
        print(f"  新增行：{ln.strip()}")
    print(f"→ {'是：base checkout 里没有这条测试，容器里找不到' if added else '否：需另查'}")


if __name__ == "__main__":
    main()
    test_patch_check()
