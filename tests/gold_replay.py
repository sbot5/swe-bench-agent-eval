"""把 gold patch 拆成 apply_patch 调用，当成一个假模型驱动整条链。

用处有两个：
  1. **端到端冒烟不花钱** —— 容器、六个工具、循环、patch 提取、preds.json、harness 评测全跑一遍，$0；
     答案还是已知的（S1 实测 gold 25/25 resolved），跑出来不是 25/25 就说明链上有 bug。
  2. **顺带量到一件事** —— search/replace 这种编辑方式，到底能不能表达真实的修复。
     gold patch 的每个 hunk 就是一对 (old_string, new_string)；哪几个 hunk 锚点不唯一，
     就是 apply_patch 在真实任务上的表达力上限（DESIGN-tools.md §四 P1 的实测依据）。
"""
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from agent.loop import FINISH_TOOL, ModelReply, ToolCall

_HUNK_HEADER = re.compile(r"^@@ .* @@")
_DIFF_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")


@dataclass(frozen=True)
class Edit:
    """一个 hunk 变成的一次编辑。"""

    path: str
    old_string: str
    new_string: str


def parse_patch(patch: str) -> list[Edit]:
    """把 unified diff 的每个 hunk 拆成一对 (old_string, new_string)。

    old 取上下文行 + 删除行，new 取上下文行 + 新增行 —— 这正好是 search/replace 要的两串。
    新建文件的 hunk 直接跳过：apply_patch 造不出文件（决定 P3）。
    """
    edits: list[Edit] = []
    path: str | None = None
    is_new_file = False
    old_lines: list[str] = []
    new_lines: list[str] = []

    def flush() -> None:
        if path is not None and old_lines and not is_new_file:
            edits.append(Edit(path=path, old_string="\n".join(old_lines), new_string="\n".join(new_lines)))
        old_lines.clear()
        new_lines.clear()

    for line in patch.splitlines():
        if (header := _DIFF_HEADER.match(line)) is not None:
            flush()
            path, is_new_file = header.group(2), False
        elif line.startswith("new file mode"):
            is_new_file = True
        elif _HUNK_HEADER.match(line):
            flush()
        elif line.startswith("\\"):  # `\ No newline at end of file`，不是内容
            continue
        elif line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            old_lines.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            new_lines.append(line[1:])

    flush()
    return edits


@dataclass
class GoldReplayClient:
    """一个假模型：每被问一次就发下一条 apply_patch，发完调 finish。

    不看 messages，也不看工具表 —— 它的作用是把链走通，不是模拟模型的判断。
    """

    edits: Sequence[Edit]
    calls: int = 0
    observed: list[str] = field(default_factory=list)

    def complete(self, messages: Sequence[dict], tools: Sequence[dict]) -> ModelReply:
        # 记下上一步的观察，跑完能看出哪几个 hunk 没打上
        if messages and messages[-1].get("role") == "tool":
            self.observed.append(messages[-1]["content"].split("\n")[1])

        index = self.calls
        self.calls += 1

        if index >= len(self.edits):
            return ModelReply(
                content="replayed every hunk",
                tool_calls=[ToolCall(id=f"call-{index}", name=FINISH_TOOL,
                                     arguments={"reason": "gold patch replayed"},
                                     raw_arguments='{"reason": "gold patch replayed"}')],
                returned_model="gold-replay",
            )

        edit = self.edits[index]
        arguments = {"path": edit.path, "old_string": edit.old_string, "new_string": edit.new_string}
        return ModelReply(
            content=f"applying hunk {index + 1}/{len(self.edits)} to {edit.path}",
            tool_calls=[ToolCall(id=f"call-{index}", name="apply_patch", arguments=arguments,
                                 raw_arguments=json.dumps(arguments))],
            returned_model="gold-replay",
        )
