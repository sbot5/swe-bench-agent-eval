"""P3 跑前探针（$0）：确认这一跑与 p2-rerun 的唯一差异就是 prompt 第 3+5 条。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/p3_preflight.py
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from agent.loop import SYSTEM_PROMPT, LoopConfig

REPO = Path(__file__).resolve().parent.parent
PROMPT_RE = re.compile(r'SYSTEM_PROMPT: Final\[str\] = """\\\n(.*?)"""', re.DOTALL)

# 三跑基线：A 组 8 条 × 3 跑，apply_patch 调用数全部为 0（EVAL-P2-rerun.md §三）
GROUP_A = [
    "django__django-10554",
    "django__django-11138",
    "pylint-dev__pylint-4551",
    "pylint-dev__pylint-8898",
    "sphinx-doc__sphinx-11510",
    "sphinx-doc__sphinx-8638",
    "sympy__sympy-17630",
    "sympy__sympy-18211",
]
# 对照：P2 相对 S5 换位的两条，查「改 prompt 有没有把本来会动手的弄坏」
CONTROLS = ["django__django-14631", "sphinx-doc__sphinx-9711"]


def md5_8(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False).stdout


def main() -> int:
    ok = True

    head_src = git("show", "HEAD:agent/loop.py")
    head_prompt = PROMPT_RE.search(head_src)
    if head_prompt is None:
        print("[1] FAIL 从 HEAD 里抠不出 SYSTEM_PROMPT")
        return 1
    head_fp, cur_fp = md5_8(head_prompt.group(1)), md5_8(SYSTEM_PROMPT)
    print(f"[1] prompt 指纹  HEAD={head_fp} (p2-rerun 用的是 bdf7e67c)  当前={cur_fp}")
    if head_fp != "bdf7e67c":
        print("    FAIL HEAD 的指纹不是 bdf7e67c —— 基线跑的不是这个 prompt，可比性不成立")
        ok = False
    if head_fp == cur_fp:
        print("    FAIL 指纹没变 —— prompt 根本没改动")
        ok = False

    # agent/ 的改动必须全部落在 prompt 那几行上；其余一行不许动
    changed = [f for f in git("diff", "--name-only", "HEAD", "--", "agent/").split() if f]
    print(f"[2] agent/ 改动文件: {changed or '(无)'}")
    if changed != ["agent/loop.py"]:
        print("    FAIL 只应该改 agent/loop.py")
        ok = False
    hunk_lines = [
        ln for ln in git("diff", "-U0", "HEAD", "--", "agent/loop.py").splitlines()
        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
    ]
    outside = [ln for ln in hunk_lines if not re.match(r"^[+-](3\.|4\.|5\.|6\.|\s)", ln)]
    print(f"[2] diff 里改动行 {len(hunk_lines)} 条，落在 How-to-work 步骤之外的 {len(outside)} 条")
    if outside:
        for ln in outside:
            print(f"    OUTSIDE {ln}")
        ok = False

    # 配置必须与 p2-rerun 相同
    cfg = LoopConfig()
    print(f"[3] max_steps={cfg.max_steps} keep_full_observations={cfg.keep_full_observations}")
    if cfg.max_steps != 40:
        print("    FAIL max_steps 不是 40 —— 那就不止改了一个变量")
        ok = False

    wanted = GROUP_A + CONTROLS
    ids_file = REPO / "groupa_ids.txt"
    got = [ln.strip() for ln in ids_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    subset = [ln.strip() for ln in (REPO / "subset_ids.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(f"[4] groupa_ids.txt {len(got)} 条；A 组 {len(GROUP_A)} + 对照 {len(CONTROLS)}")
    if got != wanted:
        print(f"    FAIL 清单对不上\n      想要: {wanted}\n      实际: {got}")
        ok = False
    missing = [i for i in wanted if i not in subset]
    if missing:
        print(f"    FAIL 这些 id 不在 subset_ids.txt 里（拼错了）: {missing}")
        ok = False

    print("\nPREFLIGHT " + ("OK —— 可以跑" if ok else "FAIL —— 先修上面的 FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
