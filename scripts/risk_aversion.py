"""§五第 0 步：在 a-reason-r1/r2 的 reasoning 里扫「风险规避」词面（$0）。

判据锁定于 docs/EVAL-risk-aversion.md §一（commit b6e1e5f），**本脚本只是它的实现**，
跑完不许改词表、分母或抽样规则：
  - 词表 §1.3：两层 RISK_HARM / RISK_UNSURE，**分开计数不合并**
  - 主分母 §1.2：areason_read.pick() 的选中轮 —— 与 H2 那 80 次**同一批轮**
  - 全量轮只回答一个问题：选段规则有没有把风险规避语言**系统性排除在选段之外**
  - 召回抽样 §1.4：无标记轮按 (实例, 轮号) 排序取第 1, 1+k, …，k = ceil(n/20)，每跑最多 20 条

⚠️ 计数口径与 scripts/areason_markers.py 一致：**按轮计**（一轮命中多个词只算一轮），
   所以能直接和 ARCH 的 80 次比。
⚠️ 词面只作导航（㊽），落点由 §1.4 读原文判。**这里打印的任何计数都不是结论。**
⚠️ 必然有假阳性（break 是 Python 关键字、regression 可能在转述 issue）——
   判据已声明由人工裁掉，**不许在这里加排除规则**，那等于事后改词表。

跑法：
  PYTHONPATH=. .venv/bin/python scripts/risk_aversion.py a-reason-r1 a-reason-r2
  PYTHONPATH=. .venv/bin/python scripts/risk_aversion.py --excerpt a-reason-r1 a-reason-r2
"""

from __future__ import annotations

import argparse
import math
import re

from areason_read import CONTROLS, GROUP_A, INFER, instances, load, pick, turns

# §1.3 的词表，一字不动。撇号写成 [’'] 只是同一词面的编码变体，不是新增词条。
MARKERS: dict[str, list[str]] = {
    "RISK_HARM": [
        r"risky", r"risk of", r"at risk",
        r"breaking (?:change|something|other|existing)",
        r"break (?:something|anything|other|existing|the)",
        r"don[’']?t want to break",
        r"(?:might|could|may) break",
        r"regression", r"side[- ]effect", r"unintended",
        r"safer to", r"too invasive",
    ],
    "RISK_UNSURE": [
        r"not sure", r"unsure", r"uncertain", r"not confident", r"more confidence",
        r"before I (?:change|modify|edit|patch)",
        r"before making (?:any )?change",
        r"(?:want|need) to be (?:sure|certain)",
        r"verify (?:this )?first", r"rather than guess", r"avoid guessing",
    ],
}
COMPILED = {k: [(p, re.compile(p, re.IGNORECASE)) for p in v] for k, v in MARKERS.items()}
CAP = 700  # 摘录窗口：命中处前后各 CAP//2，够判「不确定之后是不动手还是去查」


def hits(text: str) -> dict[str, list[str]]:
    """{层: [命中的词面]}，没命中的层不出现。"""
    out: dict[str, list[str]] = {}
    for layer, pats in COMPILED.items():
        got = [src for src, rx in pats if rx.search(text)]
        if got:
            out[layer] = got
    return out


def rows(run: str) -> list[dict]:
    """每实例一行：选段内/全量的命中轮号，按 §1.2 两个分母各算一遍。"""
    out = []
    for iid in instances(run):
        if iid not in GROUP_A + CONTROLS:
            continue
        steps = load(run, iid)
        if steps is None:
            continue
        tmap, picked = turns(steps), pick(steps)
        rec: dict = {
            "iid": iid,
            "group": "A" if iid in GROUP_A else "B",
            "all_turns": sorted(tmap),
            "sel_turns": sorted(picked),
            "sel": {k: [] for k in MARKERS},
            "full": {k: [] for k in MARKERS},
            "bare": [],
            "words": {},
        }
        for i in rec["all_turns"]:
            h = hits(tmap[i]["reasoning"] or "")
            in_sel = i in picked
            for layer, got in h.items():
                rec["full"][layer].append(i)
                if in_sel:
                    rec["sel"][layer].append(i)
                for w in got:
                    rec["words"][w] = rec["words"].get(w, 0) + 1
            if in_sel and not h:
                rec["bare"].append(i)
        out.append(rec)
    return out


def sample(recs: list[dict]) -> tuple[int, list[tuple[str, int]]]:
    """§1.4 的召回抽样：跨实例把无标记轮排成一列，等间隔取，最多 20 条。"""
    pool = sorted((r["iid"], i) for r in recs for i in r["bare"])
    if not pool:
        return 0, []
    k = max(1, math.ceil(len(pool) / 20))
    return k, pool[::k][:20]


def report(run: str, recs: list[dict]) -> None:
    print(f"\n=============== {run} ===============")
    hdr = (f"{'实例':<16}{'组':<4}{'选段轮':<7}{'HARM':<6}{'UNSURE':<8}{'无标记':<8}"
           f"{'全量轮':<7}{'全HARM':<8}{'全UNSURE':<10}选段外命中轮")
    print(hdr)
    print("-" * 96)
    for r in recs:
        outside = sorted(set(r["full"]["RISK_HARM"] + r["full"]["RISK_UNSURE"])
                         - set(r["sel"]["RISK_HARM"] + r["sel"]["RISK_UNSURE"]))
        print(f"{r['iid'].split('__')[-1]:<16}{r['group']:<4}{len(r['sel_turns']):<7}"
              f"{len(r['sel']['RISK_HARM']):<6}{len(r['sel']['RISK_UNSURE']):<8}"
              f"{len(r['bare']):<8}{len(r['all_turns']):<7}"
              f"{len(r['full']['RISK_HARM']):<8}{len(r['full']['RISK_UNSURE']):<10}{outside}")

    for tag, sub in (("A 组", [r for r in recs if r["group"] == "A"]),
                     ("B 组(对照)", [r for r in recs if r["group"] == "B"]),
                     ("合计", recs)):
        sel = sum(len(r["sel_turns"]) for r in sub)
        allt = sum(len(r["all_turns"]) for r in sub)
        h = sum(len(r["sel"]["RISK_HARM"]) for r in sub)
        u = sum(len(r["sel"]["RISK_UNSURE"]) for r in sub)
        fh = sum(len(r["full"]["RISK_HARM"]) for r in sub)
        fu = sum(len(r["full"]["RISK_UNSURE"]) for r in sub)
        bare = sum(len(r["bare"]) for r in sub)
        print(f"  {tag:<12}选段 {sel} 轮 / 全量 {allt} 轮｜选段内 HARM {h} · UNSURE {u} · "
              f"无标记 {bare}｜全量 HARM {fh} · UNSURE {fu}")

    words: dict[str, int] = {}
    for r in recs:
        for w, n in r["words"].items():
            words[w] = words.get(w, 0) + n
    print(f"  命中词面频次（全量，按轮次）：{dict(sorted(words.items(), key=lambda x: -x[1]))}")
    k, picked = sample(recs)
    print(f"  §1.4 召回抽样 k={k}，抽 {len(picked)} 轮："
          f"{[(i.split('__')[-1], t) for i, t in picked]}")


def excerpt(run: str, recs: list[dict]) -> None:
    """命中轮给 ±CAP//2 窗口，抽样轮给首尾各 CAP//2 —— 供 §1.4 逐条读原文判。"""
    out = [f"# {run} —— 风险规避词面摘录（脚本产物；判据 docs/EVAL-risk-aversion.md §一）\n",
           "⚠️ 窗口是导航用的节选，判不准的轮回 reasoning-excerpt.md 或原始 traj 读全文。\n"]
    _, picked = sample(recs)
    smp = {(i, t) for i, t in picked}
    for r in recs:
        steps = load(run, r["iid"])
        tmap = turns(steps) if steps else {}
        hit_turns = sorted(set(r["full"]["RISK_HARM"] + r["full"]["RISK_UNSURE"]))
        mine = [(t, "命中") for t in hit_turns] + \
               [(t, "抽样") for i, t in sorted(smp) if i == r["iid"]]
        if not mine:
            continue
        out.append(f"\n## {r['iid']}  [{r['group']} 组]  选段轮={r['sel_turns']}\n")
        for i, kind in sorted(mine):
            text = tmap[i]["reasoning"] or ""
            tag = "选段内" if i in r["sel_turns"] else "选段外"
            if kind == "命中":
                h = hits(text)
                spans = []
                for layer, got in h.items():
                    for w in got:
                        m = re.search(w, text, re.IGNORECASE)
                        if m:
                            lo, hi = max(0, m.start() - CAP // 2), m.end() + CAP // 2
                            spans.append(f"[{layer} / {w} @{m.start()}]\n…{text[lo:hi]}…")
                body = "\n\n".join(spans)
                head = f"### 轮 {i}  {tag}  命中 {[f'{k2}:{v}' for k2, v in h.items()]}"
            else:
                body = (text if len(text) <= CAP else
                        f"{text[:CAP // 2]}\n…[中略，全长 {len(text)} 字符]…\n{text[-CAP // 2:]}")
                head = f"### 轮 {i}  {tag}  §1.4 召回抽样（无标记轮）"
            out.append(f"{head}  工具={tmap[i]['tools']}\n")
            out.append("```\n" + (body or "(空)") + "\n```\n")
    dest = INFER / run / "risk-aversion-excerpt.md"
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"写出 {dest}（{dest.stat().st_size} 字节）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--excerpt", action="store_true")
    a = ap.parse_args()
    for run in a.runs:
        recs = rows(run)
        report(run, recs)
        if a.excerpt:
            excerpt(run, recs)
    print("\n⚠️ 以上全是词面导航，不是落点。落点按 §1.4 读原文判，真阳性须附原文引用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
