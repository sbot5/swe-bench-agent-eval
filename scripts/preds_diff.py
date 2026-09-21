"""逐条比两份 preds.json 的 model_patch，忽略键的顺序（并发跑完的顺序本来就不定）。

C23/C24 的回归闸：改了请求形状之后，gold 回放的 66 个 hunk 必须仍打出**逐字节相同**的 patch。
文件级 diff 会被键顺序刷屏，所以比的是 instance_id → model_patch 这张映射。

    PYTHONPATH=. .venv/bin/python scripts/preds_diff.py results/inference/A/preds.json results/inference/B/preds.json
"""
import json
import sys
from pathlib import Path


def main(left, right):
    a = json.loads(Path(left).read_text(encoding="utf-8"))
    b = json.loads(Path(right).read_text(encoding="utf-8"))

    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    differing = sorted(k for k in set(a) & set(b) if a[k]["model_patch"] != b[k]["model_patch"])

    print(f"{len(a)} vs {len(b)} instances")
    print(f"only in left : {only_a}")
    print(f"only in right: {only_b}")
    print(f"patches differing: {len(differing)} {differing}")
    identical = not (only_a or only_b or differing)
    print("IDENTICAL" if identical else "DIFFERENT")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
