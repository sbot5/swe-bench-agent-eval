"""三跑锚点：S4 / S5 / P2 的「元 / 百万输入 token」。
若 S4 与 S5 一致而 P2 翻倍 → 价格在 09-17 前稳定，异常出在 P2 这一跑本身。
"""
import json, pathlib

def toks(run):
    ti = to = tn = 0
    p = pathlib.Path(f"results/inference/{run}")
    if not p.exists():
        return None
    for tf in sorted(p.glob("*.traj.json")):
        d = json.loads(tf.read_text())
        seen = {}
        for st in d.get("steps", []):
            seen.setdefault(st["index"], (st["prompt_tokens"], st["completion_tokens"]))
        ti += sum(v[0] for v in seen.values())
        to += sum(v[1] for v in seen.values())
        tn += len(seen)
    return ti, to, tn, len(list(p.glob("*.traj.json")))

runs = [("s4-mine", 2.24, "09-17 S4 10 条"),
        ("s5-mine", 5.27, "09-17 S5 25 条"),
        ("p2-mine", 11.14, "09-18 P2 25 条(+冒烟并入)")]
print(f"{'跑次':<28}{'输入 tok':>12}{'输出 tok':>11}{'轮':>6}{'余额差':>8}{'元/M入':>9}{'元/轮':>8}")
for run, yuan, label in runs:
    t = toks(run)
    if not t:
        print(f"{label:<28} (找不到 results/inference/{run})")
        continue
    ti, to, tn, n = t
    print(f"{label:<28}{ti:>12,}{to:>11,}{tn:>6}{yuan:>8.2f}{yuan/(ti/1e6):>9.2f}{yuan/tn:>8.4f}")
