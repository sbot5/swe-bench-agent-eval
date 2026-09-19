"""ReAct 循环：think -> act -> observe，直到终止。工具、模型客户端都由调用方注入。

这一层不认识 Docker，也不认识 SWE-bench：拿到的是「一段任务描述 + 一组已绑好 env 的工具 + 一个模型客户端」。
注入而不是内建，是为了能用假客户端把整条链跑通而不花钱（决定 C13）—— tests/ 的端到端冒烟就靠它。
为什么是 ReAct、上下文裁剪停在哪、三条异常路径怎么定：docs/DESIGN-loop.md
"""
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum, auto, unique
from typing import Any, Final, Protocol

from agent.observation import FailureCategory, Observation, ToolStatus

MAX_STEPS: Final[int] = 40
COST_LIMIT: Final[float] = 0.50
WALL_CLOCK_LIMIT: Final[float] = 1800.0
KEEP_FULL_OBSERVATIONS: Final[int] = 5
MAX_CONSECUTIVE_TOOL_ERRORS: Final[int] = 5
MAX_FILE_EDIT_FAILURES: Final[int] = 3
MAX_EMPTY_REPLIES: Final[int] = 2
FINISH_TOOL: Final[str] = "finish"
_ELIDED_PREFIX: Final[str] = "[observation elided to save context]"


@unique
class StopReason(StrEnum):
    """一条实例为什么停下来。进 trajectory，也是归因表「Agent 侧」那一列的行标签（决定 C5）。"""

    FINISHED = auto()
    MAX_STEPS = auto()
    COST_LIMIT = auto()
    WALL_CLOCK = auto()
    TOOL_ERROR_STREAK = auto()
    EMPTY_REPLIES = auto()
    API_ERROR = auto()
    CONTEXT_OVERFLOW = auto()


class ContextOverflow(Exception):
    """模型说上下文装不下了。循环接住它裁得更狠再试一次，而不是直接放弃（决定 C11）。"""


class ModelUnavailable(Exception):
    """重试之后模型仍然叫不动。整条实例作废，但整批不停（决定 C12）。"""


@dataclass(frozen=True)
class ToolCall:
    """模型要调的一个工具。arguments 已经从 JSON 解析过；解析失败时 error 非空、arguments 为空。"""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    error: str | None = None


@dataclass(frozen=True)
class ModelReply:
    """模型一次回复的结果快照。

    returned_model 是**响应里**的模型名，不是请求时写的那个 —— 中转站有没有偷换模型只能靠它查
    （执行计划 §八 的悬置项，在这里落实；决定 C15）。

    后三个缓存/推理读数默认 **None 而不是 0**：None = 供应商这次没给这个字段（仪器没读到），
    0 = 真的一次都没命中。混成 0 就是 `cost=$0.0000` 那个坑的翻版 —— 假读数和真读数长得一样（决定 C20）。
    """

    content: str
    tool_calls: list[ToolCall]
    cost: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    returned_model: str = ""
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None
    reasoning_tokens: int | None = None


class ModelClient(Protocol):
    """循环只要求模型客户端做一件事：给消息和工具表，回一个 ModelReply。"""

    def complete(self, messages: Sequence[dict], tools: Sequence[dict]) -> ModelReply: ...


@dataclass
class StepRecord:
    """trajectory 的一行。三周后不看代码，光读这张表要能看出它为什么没解出来（决定 C6）。"""

    index: int
    thought: str
    tool_name: str
    tool_args: dict[str, Any]
    status: str
    failure_category: str | None
    summary: str
    duration: float
    cost: float
    prompt_tokens: int
    completion_tokens: int
    returned_model: str
    # 缓存/推理读数，口径同 ModelReply：None = 供应商没给，0 = 真的没命中（决定 C20）
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass
class EpisodeResult:
    """一条实例跑完的全部结果。patch 由调用方在循环外提取，这一层不碰 git（决定 G1）。"""

    instance_id: str
    stop_reason: StopReason
    steps: list[StepRecord] = field(default_factory=list)
    total_cost: float = 0.0
    total_duration: float = 0.0
    api_calls: int = 0
    finish_reason: str = ""
    error: str = ""


@dataclass(frozen=True)
class LoopConfig:
    """三个终止条件 + 三条异常路径的阈值。全部有默认值，跑之前只改要改的那个。"""

    max_steps: int = MAX_STEPS
    cost_limit: float = COST_LIMIT
    wall_clock_limit: float = WALL_CLOCK_LIMIT
    keep_full_observations: int = KEEP_FULL_OBSERVATIONS
    max_consecutive_tool_errors: int = MAX_CONSECUTIVE_TOOL_ERRORS
    max_file_edit_failures: int = MAX_FILE_EDIT_FAILURES
    max_empty_replies: int = MAX_EMPTY_REPLIES


SYSTEM_PROMPT: Final[str] = """\
You are fixing one issue in a Python repository that is already checked out at /testbed.

You work only through the tools listed below. The container has no network access: nothing can be
downloaded, fetched or cloned, so every answer has to come from the code in front of you.
Every tool answers with <summary>, sometimes <content>, and <next_actions>. When a tool reports an error,
read its <next_actions> before trying anything else — they tell you both what to retry and when to stop.

How to work:
1. Find the code the issue is about, with search_code and list_files.
2. read_file the relevant code before editing it. Never edit text you have not read in this session.
3. Try to reproduce the reported behaviour with run_python before you change anything. Reading code tells
   you what it should do; running it tells you what it does. Keep that script — you will rerun it to check
   your fix. If two attempts do not reproduce it, say in one line why, then go to step 4 anyway and fix the
   cause you read in the code: a fix you could not reproduce first may still be right, no fix scores zero.
4. Make the smallest change that fixes the reported behaviour, with apply_patch.
5. If you have a reproduction script, rerun it to confirm the behaviour changed. Then run the tests that
   cover the code you edited, with run_tests.
6. Call git_diff to check you changed only what you meant to, then call finish.

Rules that matter for how your work is graded:
- Change repository files with apply_patch, not with run_python. apply_patch checks that the text you are
  replacing is really there; a script that rewrites a file silently does the wrong thing when it is wrong.
- Do not modify or add tests. Your change is graded by tests you cannot see.
- Do not undo your change before finishing; an empty diff scores zero.
- Fix the cause described in the issue, not just the one example in it.
- If three edits to the same file fail in a row, stop editing that file and re-read it instead.
"""

_TOOL_SCHEMAS: Final[list[dict]] = [
    {
        "name": "list_files",
        "description": "List files and directories under a path in the repository, up to a given depth.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory relative to the repo root. Defaults to '.'."},
                "depth": {"type": "integer", "description": "How many levels to show. Defaults to 2."},
            },
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search the repository by content and return matching lines with surrounding context. "
            "The pattern is a Perl-compatible regex unless fixed_string is true."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "What to search for."},
                "path": {"type": "string", "description": "File or directory to search in. Defaults to '.'."},
                "fixed_string": {"type": "boolean", "description": "Search the pattern literally, not as a regex."},
                "context": {"type": "integer", "description": "Lines of context around each match, 0-10. Defaults to 2."},
                "max_results": {"type": "integer", "description": "How many matches to show. Defaults to 20."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file with line numbers, starting at offset for at most limit lines.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File relative to the repo root."},
                "offset": {"type": "integer", "description": "First line to read, 1-based. Defaults to 1."},
                "limit": {"type": "integer", "description": "How many lines to read. Defaults to 200."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "apply_patch",
        "description": (
            "Replace old_string with new_string in one file. old_string must appear exactly once in that file "
            "and must be copied verbatim from read_file output, without the line-number column. "
            "This tool cannot create files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File relative to the repo root."},
                "old_string": {"type": "string", "description": "Text to replace, unique within the file."},
                "new_string": {"type": "string", "description": "Text to put in its place."},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "run_tests",
        "description": "Run tests in the repository and report which ones fail. TARGET_HINT",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "What to run. TARGET_HINT"},
                "timeout": {"type": "integer", "description": "Seconds to allow, at most 900. Defaults to 300."},
            },
            "required": ["target"],
        },
    },
    {
        "name": "run_python",
        "description": (
            "Run a one-off Python script in the repository environment and return its output and exit code. "
            "Use it to reproduce the reported behaviour before you fix it, and to check the fix afterwards. "
            "The script runs in /testbed, so it can import the repository code. Nothing is remembered between "
            "calls, and the container has no network."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The whole script, exactly as you would write it in a .py file.",
                },
                "timeout": {"type": "integer", "description": "Seconds to allow, at most 300. Defaults to 60."},
            },
            "required": ["code"],
        },
    },
    {
        "name": "git_diff",
        "description": "Show everything you have changed so far, as a diff against the original checkout.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Limit the diff to this path. Defaults to '.'."},
            },
            "required": [],
        },
    },
    {
        "name": FINISH_TOOL,
        "description": (
            "Declare the work done and stop. Call this only after run_tests and git_diff show the change "
            "is complete and correct."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "One sentence on what you changed and why it fixes the issue.",
                },
            },
            "required": ["reason"],
        },
    },
]


def build_tool_schemas(target_hint: str = "") -> list[dict]:
    """把工具表拼成 OpenAI function calling 的形状，run_tests 的目标写法按仓库替换（决定 C3）。"""
    hint = target_hint or "Name a test file, e.g. 'path/to/tests/test_module.py'."
    return [
        {
            "type": "function",
            "function": {
                **schema,
                "description": schema["description"].replace("TARGET_HINT", hint),
                "parameters": {
                    **schema["parameters"],
                    "properties": {
                        name: {**spec, "description": spec["description"].replace("TARGET_HINT", hint)}
                        for name, spec in schema["parameters"]["properties"].items()
                    },
                },
            },
        }
        for schema in _TOOL_SCHEMAS
    ]


def trim_messages(messages: Sequence[dict], keep_full: int) -> list[dict]:
    """保留最近 keep_full 条观察的全文，更早的只留「调了什么工具、结果如何」一行（决定 C8）。

    改的是 tool 消息的 content，不删消息 —— 每个 tool_call 都必须有对应的 tool 回复，删了请求就非法了。
    """
    if keep_full < 0:
        raise ValueError("keep_full must be non-negative")

    tool_indices = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    protected = set(tool_indices[-keep_full:]) if keep_full else set()

    trimmed: list[dict] = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool" or index in protected:
            trimmed.append(message)
            continue
        # 留下的那一行就是 summary：工具的第一段本来就设计成「只读这一行也知道个大概」
        head = message["content"].split("\n</summary>")[0].removeprefix("<summary>\n")
        trimmed.append({**message, "content": f"{_ELIDED_PREFIX} {head}"})
    return trimmed


def parse_tool_calls(raw_calls: Sequence[Any]) -> list[ToolCall]:
    """把供应商返回的 tool_calls 解析成 ToolCall。参数不是合法 JSON 对象时记进 error，不抛（决定 C9）。"""
    calls: list[ToolCall] = []
    for raw in raw_calls:
        arguments_text = raw.function.arguments or "{}"
        try:
            parsed = json.loads(arguments_text)
        except json.JSONDecodeError as exc:
            calls.append(ToolCall(id=raw.id, name=raw.function.name, arguments={},
                                  raw_arguments=arguments_text, error=f"arguments are not valid JSON: {exc}"))
            continue
        if not isinstance(parsed, dict):
            calls.append(ToolCall(id=raw.id, name=raw.function.name, arguments={},
                                  raw_arguments=arguments_text, error="arguments are not a JSON object"))
            continue
        calls.append(ToolCall(id=raw.id, name=raw.function.name, arguments=parsed, raw_arguments=arguments_text))
    return calls


def _bad_call(message: str, next_actions: list[str]) -> Observation:
    """模型自己把调用写坏了时的统一回答。归 INVALID_ARGUMENT，和工具内部的参数校验同一类。"""
    return Observation.error(
        failure_category=FailureCategory.INVALID_ARGUMENT,
        summary=message,
        content="",
        next_actions=next_actions,
    )


def _dispatch(
    call: ToolCall,
    tools: Mapping[str, Callable[..., Observation]],
    edit_failures: dict[str, int],
    config: LoopConfig,
) -> Observation:
    """执行一个工具调用，把「模型写坏了」和「工具自己炸了」都变成 Observation（决定 C9、C10）。"""
    if call.error is not None:
        return _bad_call(
            f"Could not read the arguments of {call.name}: {call.error}",
            ["Call the tool again with a well-formed JSON object of arguments."],
        )

    if call.name not in tools:
        return _bad_call(
            f"There is no tool called {call.name!r}",
            [f"Call one of the available tools: {', '.join(sorted(tools))}."],
        )

    # 同一个文件连续改失败 3 次就不再进容器：DESIGN-tools §四 apply_patch 错误契约里的停止条件（决定 C10）
    path = call.arguments.get("path") if call.name == "apply_patch" else None
    if isinstance(path, str) and edit_failures.get(path, 0) >= config.max_file_edit_failures:
        return _bad_call(
            f"Refusing to edit {path!r} again: {config.max_file_edit_failures} edits to it failed in a row",
            [
                f"Call read_file on {path!r} and copy the exact text you want to replace from its output.",
                "Or make the fix in a different file; this file is now blocked for editing.",
            ],
        )

    try:
        observation = tools[call.name](**call.arguments)
    except TypeError as exc:
        # 参数名对不上工具签名：模型的错，不是工具的错
        return _bad_call(
            f"{call.name} does not accept these arguments: {exc}",
            [f"Call {call.name} again using only the arguments listed in its schema."],
        )
    except Exception as exc:  # 工具自己炸了也不能停整条实例，记成环境错误继续（决定 C10）
        return Observation.error(
            failure_category=FailureCategory.IO_ERROR,
            summary=f"{call.name} raised {type(exc).__name__}: {exc}",
            content="",
            next_actions=[
                f"Retry {call.name} once with the same arguments.",
                "If it raises again, use a different tool; this is an environment problem, not an argument problem.",
            ],
        )

    if isinstance(path, str):
        if observation.status == ToolStatus.ERROR:
            edit_failures[path] = edit_failures.get(path, 0) + 1
        else:
            edit_failures.pop(path, None)  # 改对一次就清零，否则前面失败过的文件会被永久拉黑
    return observation


def run_episode(
    *,
    instance_id: str,
    problem_statement: str,
    tools: Mapping[str, Callable[..., Observation]],
    client: ModelClient,
    tool_schemas: Sequence[dict],
    config: LoopConfig = LoopConfig(),
    system_prompt: str = SYSTEM_PROMPT,
) -> tuple[EpisodeResult, list[dict]]:
    """跑一条实例的 ReAct 循环，返回 (结果, 完整消息历史)。tools 必须是已经绑好 env 的可调用对象。

    三个终止条件都在这里：步数、成本、模型声明完成；另加墙钟上限与三条异常路径（决定 C4–C12）。
    """
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"<issue>\n{problem_statement}\n</issue>"},
    ]

    result = EpisodeResult(instance_id=instance_id, stop_reason=StopReason.MAX_STEPS)
    edit_failures: dict[str, int] = {}
    error_streak = 0
    empty_streak = 0
    keep_full = config.keep_full_observations
    started = time.monotonic()

    for index in range(1, config.max_steps + 1):
        # 1. 成本和墙钟每一步开头查一次（决定 C4）
        if result.total_cost >= config.cost_limit:
            result.stop_reason = StopReason.COST_LIMIT
            break
        if time.monotonic() - started >= config.wall_clock_limit:
            result.stop_reason = StopReason.WALL_CLOCK
            break

        # 2. think：裁过的历史送进模型；撞上下文上限就裁到只剩最近一条再试，而不是直接放弃（决定 C11）
        call_started = time.monotonic()
        try:
            reply = client.complete(trim_messages(messages, keep_full), tool_schemas)
        except ContextOverflow:
            if keep_full <= 1:
                result.stop_reason = StopReason.CONTEXT_OVERFLOW
                result.error = "context window exceeded even with only the last observation kept"
                break
            keep_full = 1
            continue
        except ModelUnavailable as exc:
            result.stop_reason = StopReason.API_ERROR
            result.error = str(exc)
            break

        result.api_calls += 1
        result.total_cost += reply.cost
        think_duration = time.monotonic() - call_started

        # 3. 模型既不调工具也不声明完成：提醒一次，连续两次就停，不无限提醒（决定 C7）
        if not reply.tool_calls:
            empty_streak += 1
            messages.append({"role": "assistant", "content": reply.content})
            if empty_streak >= config.max_empty_replies:
                result.stop_reason = StopReason.EMPTY_REPLIES
                result.error = "model replied without calling any tool twice in a row"
                break
            messages.append({
                "role": "user",
                "content": "You did not call a tool. Call one of the tools, or call finish if the work is done.",
            })
            continue
        empty_streak = 0

        messages.append({
            "role": "assistant",
            "content": reply.content,
            "tool_calls": [
                {"id": call.id, "type": "function",
                 "function": {"name": call.name, "arguments": call.raw_arguments}}
                for call in reply.tool_calls
            ],
        })

        # 4. act + observe：一次回复里的每个 tool_call 都必须有回复，少一条下一轮请求就非法
        finished = False
        for call in reply.tool_calls:
            if call.name == FINISH_TOOL:
                result.finish_reason = str(call.arguments.get("reason", ""))
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": "<summary>\nStopping here.\n</summary>"})
                finished = True
                continue

            act_started = time.monotonic()
            observation = _dispatch(call, tools, edit_failures, config)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": observation.render()})

            result.steps.append(StepRecord(
                index=index,
                thought=reply.content,
                tool_name=call.name,
                tool_args=call.arguments,
                status=str(observation.status),
                failure_category=str(observation.failure_category) if observation.failure_category else None,
                summary=observation.summary,
                duration=think_duration + time.monotonic() - act_started,
                cost=reply.cost,
                prompt_tokens=reply.prompt_tokens,
                completion_tokens=reply.completion_tokens,
                returned_model=reply.returned_model,
                cache_hit_tokens=reply.cache_hit_tokens,
                cache_miss_tokens=reply.cache_miss_tokens,
                reasoning_tokens=reply.reasoning_tokens,
            ))

            # 5. 异常路径：连着错到阈值就停，而不是重试到死（决定 C10）
            error_streak = error_streak + 1 if observation.status == ToolStatus.ERROR else 0

        if finished:
            result.stop_reason = StopReason.FINISHED
            break
        if error_streak >= config.max_consecutive_tool_errors:
            result.stop_reason = StopReason.TOOL_ERROR_STREAK
            result.error = f"{error_streak} tool calls failed in a row"
            break

    result.total_duration = time.monotonic() - started
    return result, messages
