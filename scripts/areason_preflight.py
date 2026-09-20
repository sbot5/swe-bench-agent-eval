"""A 组 reasoning 对读的跑前探针（$0）。

本跑与 P3 两跑的**唯一**差异必须是 C21 仪器（reasoning_content 落盘），
prompt 与 agent/ 其余部分一行不许动 —— 否则它就不是 P3 配置的第 3、4 个样本，
【未知】③ 那 16 次动手数观测也白拿（判据 docs/EVAL-A-reasoning.md §1.2）。

跑法：cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/areason_preflight.py
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from agent.loop import SYSTEM_PROMPT, LoopConfig

REPO = Path(__file__).resolve().parent.parent
PROMPT_RE = re.compile(r'SYSTEM_PROMPT: Final\[str\] = """\\\n(.*?)"""', re.DOTALL)

P3_FINGERPRINT = "019bb6fd"  # P3 两跑用的指纹（scripts/p3_run.sh:4：bdf7e67c -> 019bb6fd）
C21_COMMIT = "5348904"       # C21 reasoning_content 落盘

GROUP_A = [
    "django__django-10554", "django__django-11138", "pylint-dev__pylint-4551",
    "pylint-dev__pylint-8898", "sphinx-doc__sphinx-11510", "sphinx-doc__sphinx-8638",
    "sympy__sympy-17630", "sympy__sympy-18211",
]
CONTROLS = ["django__django-14631", "sphinx-doc__sphinx-9711"]


def md5_8(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False).stdout


def main() -> int:
    ok = True

    # [1] prompt 指纹必须仍是 P3 的那个。C21 刻意没碰 prompt（不回传 reasoning_content，
    #     否则整棵前缀缓存树作废）—— 这里就是验它真的没碰。
    cur_fp = md5_8(SYSTEM_PROMPT)
    print(f"[1] prompt 指纹 当前={cur_fp}  P3 两跑={P3_FINGERPRINT}")
    if cur_fp != P3_FINGERPRINT:
        print("    FAIL 指纹与 P3 不同 —— 本跑不能当 P3 配置的样本，【未知】③ 那一半目的落空")
        ok = False

    # [2] agent/ 相对 HEAD 必须一个字节都没动（本跑是「不改代码，只买读数」）
    changed = [f for f in git("diff", "--name-only", "HEAD", "--", "agent/").split() if f]
    staged = [f for f in git("diff", "--cached", "--name-only", "HEAD", "--", "agent/").split() if f]
    print(f"[2] agent/ 未暂存改动: {changed or '(无)'}   已暂存: {staged or '(无)'}")
    if changed or staged:
        print("    FAIL 本跑不许改 agent/")
        ok = False

    # [3] HEAD 必须含 C21，否则仪器根本不在
    head = git("rev-parse", "--short", "HEAD").strip()
    rc = subprocess.run(["git", "merge-base", "--is-ancestor", C21_COMMIT, "HEAD"],
                        cwd=REPO, capture_output=True, text=True, check=False).returncode
    print(f"[3] HEAD={head}  含 C21({C21_COMMIT})={'是' if rc == 0 else '否'}")
    if rc != 0:
        print("    FAIL HEAD 不含 C21 —— reasoning_content 不会落盘，白花钱")
        ok = False

    # [3b] 仪器真的接在 StepRecord 上（C21 验过，这里只做在场核对，不重做）
    from agent.loop import StepRecord
    fields = {f for f in StepRecord.__dataclass_fields__}
    need = {"reasoning_content", "reasoning_tokens", "cache_hit_tokens", "cache_miss_tokens"}
    print(f"[3b] StepRecord 仪器字段齐备={need <= fields}  缺={sorted(need - fields) or '(无)'}")
    if not need <= fields:
        ok = False

    # [4] 配置与 P3 相同
    cfg = LoopConfig()
    print(f"[4] max_steps={cfg.max_steps} keep_full_observations={cfg.keep_full_observations}")
    if cfg.max_steps != 40:
        print("    FAIL max_steps 不是 40 —— 那就不止换了一个变量")
        ok = False

    # [5] 实例清单与 P3 逐条一致
    wanted = GROUP_A + CONTROLS
    got = [ln.strip() for ln in (REPO / "groupa_ids.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
    subset = [ln.strip() for ln in (REPO / "subset_ids.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(f"[5] groupa_ids.txt {len(got)} 条（A 组 {len(GROUP_A)} + 对照 {len(CONTROLS)}）")
    if got != wanted:
        print(f"    FAIL 清单对不上\n      想要: {wanted}\n      实际: {got}")
        ok = False
    missing = [i for i in wanted if i not in subset]
    if missing:
        print(f"    FAIL 这些 id 不在 subset_ids.txt 里: {missing}")
        ok = False

    print("\nPREFLIGHT " + ("OK —— 可以跑" if ok else "FAIL —— 先修上面的 FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
