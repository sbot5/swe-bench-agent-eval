"""P4 分阶段 Round：40 轮切成三段，每段换整条指令、同时换工具表（`docs/EVAL-P4-staged.md` §二）。

**这里只放 P4 这一次实验的内容** —— 骨架 system prompt、三段指令原文、切法、段→工具表。
`loop.py` 那边只有一个通用的 `stage_notes` 钩子，它不知道「三段」这回事，也不该知道。

⚠️ 指令是**在消息尾部追加**，`messages[0]` 全程不变（决定 C25）：中途改写 system prompt 会让整棵
前缀缓存树作废，而实测未命中单价是命中的 50 倍【原文 `docs/EVAL-P2-rerun.md:125-143`】。
追加的消息用 `role="system"`，与 `tools_changed_message` 同形；`trim_messages` 只折叠 `role=="tool"`
的消息【原文 `agent/loop.py:386`】，所以段指令不会被 C24 的折叠吃掉。

⚠️ 骨架 prompt **删掉了原 SYSTEM_PROMPT 的「How to work」六步**。不删的话六步与段指令并存、
互相矛盾，正是 P3 ⒜ 那个「只改第 3 条会让 prompt 自相矛盾」的同型。grading rules 五条保留不动。
"""

from __future__ import annotations

import hashlib
from typing import Final

from agent.loop import EpisodeResult

# 切法【判断 2026-09-22 定，依据 `scripts/stage_budget.py` 的 $0 读数】：
# B 组（会动手的实例）首刀轮号两跑中位 9 / 11，12 轮覆盖 62% / 53% —— 即「正常实例到这儿都动手了」；
# 首刀之后还要用的轮数中位 14.5 / 9，所以 Implement 20 + Verify 8 = 28 有余量。
# ⚠️ 两跑首刀轮号自己的配对差中位 4.5、max 28（㊾：这个量自己也在摆），切法不是最优解，是有据可查的一个点。
COLLECT_END: Final[int] = 12
IMPLEMENT_END: Final[int] = 32
TOTAL_STEPS: Final[int] = 40

SKELETON_SYSTEM_PROMPT: Final[str] = """\
You are fixing one issue in a Python repository that is already checked out at /testbed.

You work only through the tools listed below. The container has no network access: nothing can be
downloaded, fetched or cloned, so every answer has to come from the code in front of you.
Every tool answers with <summary>, sometimes <content>, and <next_actions>. When a tool reports an error,
read its <next_actions> before trying anything else — they tell you both what to retry and when to stop.

Your work is split into three rounds. Each round arrives as a <round> message and replaces the previous
round's instructions entirely — when a new round starts, the previous round's instructions no longer apply.
The set of tools you are given changes with the round; the tool list sent with each request is the
authoritative one.

Rules that matter for how your work is graded:
- Change repository files with apply_patch, not with run_python. apply_patch checks that the text you are
  replacing is really there; a script that rewrites a file silently does the wrong thing when it is wrong.
- Do not modify or add tests. Your change is graded by tests you cannot see.
- Do not undo your change before finishing; an empty diff scores zero.
- Fix the cause described in the issue, not just the one example in it.
- If three edits to the same file fail in a row, stop editing that file and re-read it instead.
"""

ROUND_COLLECT: Final[str] = f"""\
<round name="COLLECT" number="1" of="3" steps="1-{COLLECT_END}">
Your only job in this round is to understand the issue well enough to fix it.

1. Find the code the issue is about, with search_code and list_files.
2. read_file the code you think is responsible. Never plan an edit to text you have not read.
3. Try to reproduce the reported behaviour with run_python. Keep that script — you will rerun it later.
   If two attempts do not reproduce it, say in one line why, and spend the rest of this round reading the
   code instead: a fix you could not reproduce first may still be right.

You cannot change anything in this round — apply_patch is not available until round 2. Do not spend this
round trying to work out how this project fixed the issue upstream: that fix is not in this container and
not in your tools, and the round will end whether or not you have found it.
</round>
"""

ROUND_IMPLEMENT: Final[str] = f"""\
<round name="IMPLEMENT" number="2" of="3" steps="{COLLECT_END + 1}-{IMPLEMENT_END}">
Round 1 is over and its instructions no longer apply. Whatever understanding you have now is what you
fix with. Your job in this round is to land a change.

1. Make the smallest change that fixes the reported behaviour, with apply_patch.
2. If an edit fails, read_file that region again and retry with the exact text you just read.
3. Rerun your reproduction script with run_python if you have one, then run_tests on the code you edited.

search_code and list_files are no longer available: this round is not for looking for more code. A fix you
are not fully certain about is worth more than no fix — an empty diff scores zero.
</round>
"""

ROUND_VERIFY: Final[str] = f"""\
<round name="VERIFY" number="3" of="3" steps="{IMPLEMENT_END + 1}-{TOTAL_STEPS}">
Round 2 is over and its instructions no longer apply. Your job in this round is to make sure what you
already changed is correct and complete, not to start a new line of work.

1. run_tests on the tests that cover the code you edited.
2. git_diff to check you changed only what you meant to, and that the diff is not empty.
3. Use apply_patch only to fix what the tests or the diff show is wrong. Then call finish.

run_python, search_code and list_files are no longer available. Call finish before you run out of steps.
Whatever is in the diff at the end is what gets graded, so never undo your change to "clean up".
</round>
"""

# 段→声明给模型的工具集。`finish` 必须全段保留，否则 `_validated_declaration` 当场抛 ValueError。
# read_file 三段都留：摘掉读会打爆 apply_patch 的锚点匹配（gold 回放 66/66 那条性质靠它）。
#
# ⚠️ **顺序必须与 `build_tool_schemas()` 的原顺序一致**，由 `test_staged.py` 钉死。
# `select_tool_schemas` 保持原 schema 顺序（C23：重排会让请求前缀变一遍），而 `StepRecord.tools_declared`
# 落的是这里的顺序 —— 两边不一致，落盘记录就与真正发出去的工具表对不上，后面按 `tools_declared`
# 重建每轮工具表的分析（C24 的 `scripts/cache_sim.py` 就是这么做的）会拿到一个从未发生过的顺序。
STAGE_TOOLS: Final[dict[str, tuple[str, ...]]] = {
    "COLLECT": ("list_files", "search_code", "read_file", "run_python", "finish"),
    "IMPLEMENT": ("read_file", "apply_patch", "run_tests", "run_python", "git_diff", "finish"),
    "VERIFY": ("read_file", "apply_patch", "run_tests", "git_diff", "finish"),
}

STAGE_NOTES: Final[dict[int, str]] = {
    1: ROUND_COLLECT,
    COLLECT_END + 1: ROUND_IMPLEMENT,
    IMPLEMENT_END + 1: ROUND_VERIFY,
}


def stage_of(index: int) -> str:
    """第 index 步属于哪一段。固定轮数切，不看信号（§2.1 ⒝）。

    信号触发被否掉的理由是触发器自己在摆：T 跑间极差中位 13 轮，且 `django-11138` 四跑全部 T=None
    —— 用它当边界，那条实例永远进不了 Implement 段【原文 `docs/EVAL-repair-gate-N.md`】。
    """
    if index <= COLLECT_END:
        return "COLLECT"
    if index <= IMPLEMENT_END:
        return "IMPLEMENT"
    return "VERIFY"


def tool_policy(index: int, result: EpisodeResult) -> tuple[str, ...]:
    """`run_episode(tool_policy=...)` 要的那个可调用对象。只看步号，不看 result（固定轮数切）。"""
    del result  # 固定轮数切法里用不到；留着形参是为了符合 ToolPolicy 的签名
    return STAGE_TOOLS[stage_of(index)]


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def fingerprint() -> dict[str, object]:
    """§四 第 5 条要求写进文件的指纹：改了任何一段指令或切法，这里的 md5 就变。"""
    return {
        "cut": [COLLECT_END, IMPLEMENT_END, TOTAL_STEPS],
        "system_prompt_md5": _md5(SKELETON_SYSTEM_PROMPT),
        "round_md5": {
            "COLLECT": _md5(ROUND_COLLECT),
            "IMPLEMENT": _md5(ROUND_IMPLEMENT),
            "VERIFY": _md5(ROUND_VERIFY),
        },
        "stage_tools": {stage: list(names) for stage, names in STAGE_TOOLS.items()},
        "stage_notes_at": sorted(STAGE_NOTES),
    }


if __name__ == "__main__":  # python3 -m agent.staged 打印指纹，跑前抄进 EVAL 文档
    import json

    print(json.dumps(fingerprint(), indent=2, ensure_ascii=False))
