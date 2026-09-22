"""P4 跑前冒烟（$0）：用假模型把 `--staged` 的配置跑满 40 步，把三段边界打出来供肉眼读。

`docs/EVAL-P4-staged.md` §四 第 3 条原话是「冒烟 p4-smoke 1 条，肉眼读一遍三段的 Round 指令真的换了」。
真跑 1 条 40 轮约 ¥0.2，而它要看的三件事（指令有没有换、工具表有没有跟着换、前缀有没有断）
在假模型下全都看得见，而且能逐条断言 —— 所以这里用 $0 的版本，真跑冒烟另说。

⚠️ 它证不了「模型会不会照做」。那是真跑才能答的，判据在同一份文档的 §三。

    PYTHONPATH=. .venv/bin/python scripts/p4_preflight.py
"""
from __future__ import annotations

import json

from agent import staged
from agent.loop import LoopConfig, ModelReply, ToolCall, build_tool_schemas, run_episode
from agent.observation import Observation


class Recorder:
    """假模型：每一步都调 read_file，同时把「这一步看见了什么」记下来。"""

    def __init__(self) -> None:
        self.views: list[list[dict]] = []
        self.tools: list[list[str]] = []

    def complete(self, messages, tools):
        self.views.append(list(messages))
        self.tools.append([schema["function"]["name"] for schema in tools])
        arguments = {"path": "a.py"}
        return ModelReply(
            content="thinking",
            tool_calls=[ToolCall(id=f"c{len(self.views)}", name="read_file",
                                 arguments=arguments, raw_arguments=json.dumps(arguments))],
            cost=0.0,
            returned_model="fake",
        )


def main() -> int:
    recorder = Recorder()
    tools = {name: (lambda **_: Observation.ok(summary="did it", content="body"))
             for name in ("list_files", "search_code", "read_file", "apply_patch",
                          "run_tests", "run_python", "git_diff")}
    result, messages = run_episode(
        instance_id="fake__fake-1",
        problem_statement="an issue",
        tools=tools,
        client=recorder,
        tool_schemas=build_tool_schemas(),
        config=LoopConfig(max_steps=staged.TOTAL_STEPS),
        system_prompt=staged.SKELETON_SYSTEM_PROMPT,
        tool_policy=staged.tool_policy,
        stage_notes=staged.STAGE_NOTES,
    )

    print("== 指纹（抄进 EVAL-P4-staged.md §2.1）==")
    print(json.dumps(staged.fingerprint(), indent=2, ensure_ascii=False))

    print(f"\n== 跑满了吗：{result.stop_reason}，{len(recorder.views)} 步 ==")

    print("\n== 逐步声明的工具集（只在边界变）==")
    previous: list[str] | None = None
    for step, names in enumerate(recorder.tools, start=1):
        if names != previous:
            print(f"  step {step:>2} [{staged.stage_of(step):<9}] {', '.join(names)}")
            previous = names

    print("\n== 三段指令原文（肉眼读：换了没有、有没有说清上一段不再适用）==")
    for step in sorted(staged.STAGE_NOTES):
        print(f"\n---- 在 step {step} 追加，此时属于 {staged.stage_of(step)} 段 ----")
        print(staged.STAGE_NOTES[step].rstrip())

    system_texts = [m["content"] for m in messages if m["role"] == "system"]
    rounds = [text for text in system_texts if text.startswith("<round")]
    others = [text for text in system_texts if not text.startswith("<round")]

    print("\n== 自检 ==")
    checks: list[tuple[str, bool]] = [
        ("messages[0] 全程没被改写", {view[0]["content"] for view in recorder.views}
         == {staged.SKELETON_SYSTEM_PROMPT}),
        ("三条段指令按顺序到位，一条不多一条不少",
         rounds == [staged.STAGE_NOTES[step] for step in sorted(staged.STAGE_NOTES)]),
        ("除了开头那条，其余 system 消息只有工具变更通知",
         others[0] == staged.SKELETON_SYSTEM_PROMPT
         and all(text.startswith("<tools_changed>") for text in others[1:])),
        ("每一步声明的工具集 = 该步所属段的工具集",
         all(set(names) == set(staged.STAGE_TOOLS[staged.stage_of(step)])
             for step, names in enumerate(recorder.tools, start=1))),
        ("Collect 段确实拿不到 apply_patch",
         all("apply_patch" not in recorder.tools[step - 1]
             for step in range(1, staged.COLLECT_END + 1))),
        ("Implement/Verify 段确实拿不到 search_code",
         all("search_code" not in recorder.tools[step - 1]
             for step in range(staged.COLLECT_END + 1, staged.TOTAL_STEPS + 1))),
    ]
    failed = 0
    for label, passed in checks:
        print(f"  [{'ok ' if passed else 'FAIL'}] {label}")
        failed += 0 if passed else 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
