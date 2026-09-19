"""比对 gold 回放的 preds：按 instance_id 逐条比 model_patch，不比整文件。

为什么不用整文件 md5（09-19 踩到）：preds.json 是 4 个 worker 并发写的，
**键的顺序不稳定** —— p3 与 p2 的整文件 md5 不同，diff 出来却只是 django-11138
在 JSON 里的位置差了几行，patch 内容一字不差。整文件 md5 会把「顺序不同」误报成
「内容不同」，是⑩㉘ 同型的判据选错。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p3_replay_compare.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NEW = "p3-gold-replay"
OLD = ["p2-gold-replay", "c20-gold-replay"]


def load(run_id: str) -> dict[str, str]:
    path = REPO / "results" / "inference" / run_id / "preds.json"
    return {k: v["model_patch"] for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def main() -> int:
    new = load(NEW)
    ok = True
    for old_id in OLD:
        old = load(old_id)
        only_new = sorted(set(new) - set(old))
        only_old = sorted(set(old) - set(new))
        differing = sorted(k for k in set(new) & set(old) if new[k] != old[k])
        same = len(set(new) & set(old)) - len(differing)
        print(f"{NEW} vs {old_id}: {len(new)} vs {len(old)} 条；"
              f"逐字节相同 {same}，内容不同 {len(differing)}，只在新 {len(only_new)}，只在旧 {len(only_old)}")
        for k in differing:
            print(f"    DIFFER {k}: {len(old[k])}ch -> {len(new[k])}ch")
        for k in only_new + only_old:
            print(f"    MISSING {k}")
        if differing or only_new or only_old:
            ok = False

    print("\n" + ("所有 patch 逐字节相同 —— 假模型不读 prompt，改 prompt 对回放是 no-op，符合预期"
                  if ok else "有差异 —— 改 prompt 不该影响假模型回放，去查"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
