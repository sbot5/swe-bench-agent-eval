"""所有工具的统一返回形状：Observation，以及它的状态、失败类别、渲染和截断。

决定、实测、已纠正的错误：docs/DESIGN-observation.md
"""
from dataclasses import dataclass, field
from enum import StrEnum, auto, unique
from typing import Final, Self

# render() 截断 content 的阈值（字符）。与 mini-swe-agent 对齐是为了控制变量，不是最优值（决定 22）
MAX_CONTENT_CHARS: Final = 10000

class ToolStatus(StrEnum):
    """工具有没有完成它的活，不是好消息 / 坏消息（决定 1、3）。

    run_tests 挂了 3 条 -> OK；search_code 0 结果 -> OK；read_file 路径不存在 -> ERROR。
    """

    OK = auto()
    ERROR = auto()

@unique
class FailureCategory(StrEnum):
    """归因表的行标签。值是成员名的小写，直接写进 trajectory JSON（决定 4–6）。"""

    ANCHOR_AMBIGUOUS = auto()
    ANCHOR_NOT_FOUND = auto()
    PATH_NOT_FOUND = auto()
    PATH_OUTSIDE_ROOT = auto()
    FILE_UNCHANGED = auto()
    IO_ERROR = auto()
    TIMEOUT = auto()
    UNCLASSIFIED = auto()
    INVALID_ARGUMENT = auto()

    def is_env_error(self) -> bool:
        """IO_ERROR / TIMEOUT 算环境的，其余算模型或工具的（决定 7）。"""
        return self in { FailureCategory.IO_ERROR, FailureCategory.TIMEOUT }

@dataclass(frozen=True)
class Observation:
    """所有工具的统一返回形状，也是模型看这个世界的唯一管道。

    summary / content / next_actions 渲染给模型：只读这一段能不能定下一步。
    status / failure_category 进 trajectory 给我：三周后不看代码能不能读出为什么失败。
    不变量（构造时检查）：ERROR 必须带 failure_category 和非空 next_actions（决定 8–11）。
    """

    status: ToolStatus
    """工具有没有完成它的活。loop 就靠它二分。"""

    summary: str
    """一行说清发生了什么。模型只读这一行也该知道个大概。"""

    content: str
    """正文，可能被截断。截断说明必须写在这里面 —— 不设 truncated 字段。"""

    next_actions: list[str] = field(default_factory=list)
    """下一步能做什么。error 时必须非空 —— 错误契约三件套的落点。"""

    failure_category: FailureCategory | None = None
    """归因表的行标签。成功时为 None，error 时必填。"""

    def __post_init__(self):
        if self.status == ToolStatus.ERROR:
            if not self.next_actions:
                raise ValueError("Next action is empty")
            if self.failure_category is None:
                raise ValueError("Failure category is empty")

    @classmethod
    def ok(cls, *, summary: str, content: str, next_actions: list[str] | None = None) -> Self:
        """造一个「工具正常完成」的观察。

        签名里没有 failure_category，所以造不出「OK 却带失败类别」的观察；参数全部强制关键字（决定 12–14）。
        """
        next_actions = next_actions or []  # 哨兵：默认值直接写 [] 会被所有调用共用同一个 list
        return cls(status=ToolStatus.OK, summary=summary, content=content, next_actions=next_actions)

    @classmethod
    def error(cls, failure_category: FailureCategory, *, summary: str, content: str, next_actions: list[str]) -> Self:
        """造一个「工具没能完成」的观察。

        全部必填：少传是 TypeError（签名），传空列表是 ValueError（__post_init__）。只有 failure_category 可位置传（决定 12–14）。
        """
        return cls(status=ToolStatus.ERROR, failure_category=failure_category, next_actions=next_actions, summary=summary, content=content)

    def render(self) -> str:
        """拼成模型读到的文本：summary -> content -> next_actions，XML 标签分隔，空段落不输出（决定 15–19）。"""
        parts = []
        parts.append(
            f"<summary>\n{self.summary}\n</summary>"
        )

        if self.content:
            # 截断在渲染时做，对象里存全量，归因时能看到模型没看到的部分
            result = _truncate(self.content, MAX_CONTENT_CHARS)
            parts.append(
                f"<content>\n{result}\n</content>"
            )

        if self.next_actions:
            actions = "\n".join(
                f"- {action}" for action in self.next_actions
            )

            parts.append(
                f"<next_actions>\n{actions}\n</next_actions>"
            )

        return "\n".join(parts)  # 段间分隔只由这个 join 负责，各段自己不带尾部换行

def _truncate(text: str, limit: int) -> str:
    """超过 limit 时保留头尾各 limit // 2 个字符，中间换成一行说明丢了多少。返回新字符串。

    只说丢了多少，不说怎么续读 —— 续读指令由工具写进 next_actions（决定 20–23）。
    """
    if limit < 0:
        raise ValueError("Limit must be non-negative")

    # 早返回是正确性的一部分：不截断时头尾会重叠，整段输出两遍
    if len(text) <= limit:
        return text

    half = limit // 2
    head = text[:half]
    # half 为 0 时 text[-0:] 是整串，必须特判
    tail = text[-half:] if half else ""

    middle = text[half:-half] if half else text

    omitted_chars = len(middle)
    omitted_lines = len(middle.splitlines())

    notice = (
        f"\n\n[TRUNCATED: omitted {omitted_chars} chars "
        f"/ {omitted_lines} lines; kept {half} chars from head "
        f"and {half} chars from tail]\n\n"
    )

    return head + notice + tail
