"""循环的单测：三个终止条件 + 三条异常路径，各触发一次。

异常路径是面经的崩点（「reflection 失败 3 次之后怎么处理」），所以每一条都要有可执行的证据，
而不是只写在设计文档里。用假客户端和假工具，秒级，不花钱。
"""
import json
from dataclasses import asdict

import pytest

from agent.loop import (
    ContextOverflow,
    LoopConfig,
    ModelReply,
    ModelUnavailable,
    StopReason,
    ToolCall,
    build_tool_schemas,
    run_episode,
    trim_messages,
)
from agent.observation import FailureCategory, Observation


def call(name: str, index: int = 0, **arguments) -> ToolCall:
    return ToolCall(id=f"c{index}", name=name, arguments=arguments, raw_arguments=json.dumps(arguments))


def reply(*calls: ToolCall, content: str = "thinking", cost: float = 0.0) -> ModelReply:
    return ModelReply(content=content, tool_calls=list(calls), cost=cost, returned_model="fake")


class ScriptedClient:
    """按脚本回复；脚本用完就一直重复最后一条，免得测试里还要算准次数。"""

    def __init__(self, replies, raises=None):
        self.replies = list(replies)
        self.raises = raises
        self.calls = 0
        self.seen: list[list[dict]] = []

    def complete(self, messages, tools):
        self.seen.append(list(messages))
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


def ok_tool(**_):
    return Observation.ok(summary="did it", content="body")


def failing_tool(**_):
    return Observation.error(
        failure_category=FailureCategory.ANCHOR_NOT_FOUND,
        summary="not found", content="", next_actions=["read the file first"],
    )


def episode(client, tools, **config_kwargs):
    return run_episode(
        instance_id="x__x-1", problem_statement="an issue", tools=tools, client=client,
        tool_schemas=build_tool_schemas(), config=LoopConfig(**config_kwargs),
    )


# ------------------------------------------------------------------ 终止条件

def test_finish_stops_the_loop_and_keeps_the_reason():
    client = ScriptedClient([reply(call("finish", reason="done because X"))])
    result, messages = episode(client, {"read_file": ok_tool})
    assert result.stop_reason == StopReason.FINISHED
    assert result.finish_reason == "done because X"
    # finish 也要有 tool 回复，否则下一轮请求是非法的
    assert messages[-1]["role"] == "tool"


def test_max_steps_stops_the_loop():
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=3)
    assert result.stop_reason == StopReason.MAX_STEPS
    assert len(result.steps) == 3


def test_cost_limit_stops_before_the_next_call():
    client = ScriptedClient([reply(call("read_file", path="a.py"), cost=0.4)])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=10, cost_limit=0.5)
    assert result.stop_reason == StopReason.COST_LIMIT
    assert result.api_calls == 2  # 第二次调用后成本达标，第三次就不发了


def test_wall_clock_limit_stops_the_loop():
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=10, wall_clock_limit=0.0)
    assert result.stop_reason == StopReason.WALL_CLOCK
    assert result.api_calls == 0


# ------------------------------------------------------------------ 异常路径

def test_a_streak_of_tool_errors_stops_the_loop_instead_of_retrying_forever():
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": failing_tool}, max_steps=50, max_consecutive_tool_errors=3)
    assert result.stop_reason == StopReason.TOOL_ERROR_STREAK
    assert len(result.steps) == 3


def test_a_successful_call_resets_the_error_streak():
    calls = {"n": 0}

    def flaky(**_):
        calls["n"] += 1
        return failing_tool() if calls["n"] % 2 else ok_tool()

    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": flaky}, max_steps=8, max_consecutive_tool_errors=3)
    assert result.stop_reason == StopReason.MAX_STEPS


def test_three_failed_edits_to_one_file_block_that_file_without_touching_the_tool():
    seen: list[str] = []

    def counting_edit(path, **_):
        seen.append(path)
        return failing_tool()

    client = ScriptedClient([reply(call("apply_patch", path="a.py", old_string="x", new_string="y"))])
    result, _ = episode(client, {"apply_patch": counting_edit},
                        max_steps=10, max_consecutive_tool_errors=99, max_file_edit_failures=3)
    assert seen == ["a.py"] * 3, "第 4 次起就不该再进工具了"
    assert result.steps[3].failure_category == str(FailureCategory.INVALID_ARGUMENT)
    assert "Refusing to edit" in result.steps[3].summary


def test_a_successful_edit_clears_the_block_counter():
    calls = {"n": 0}

    def flaky_edit(**_):
        calls["n"] += 1
        return ok_tool() if calls["n"] == 3 else failing_tool()

    client = ScriptedClient([reply(call("apply_patch", path="a.py", old_string="x", new_string="y"))])
    result, _ = episode(client, {"apply_patch": flaky_edit},
                        max_steps=6, max_consecutive_tool_errors=99, max_file_edit_failures=3)
    assert calls["n"] == 6, "成功一次之后计数要清零，文件不能被永久拉黑"


def test_a_reply_with_no_tool_call_is_nudged_once_then_stops():
    client = ScriptedClient([reply(content="I think I am done.")])
    result, messages = episode(client, {"read_file": ok_tool}, max_steps=10)
    assert result.stop_reason == StopReason.EMPTY_REPLIES
    assert any(m.get("role") == "user" and "did not call a tool" in m["content"] for m in messages)


def test_an_unknown_tool_name_is_answered_not_raised():
    client = ScriptedClient([reply(call("delete_everything"))])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)
    assert result.steps[0].failure_category == str(FailureCategory.INVALID_ARGUMENT)
    assert "no tool called" in result.steps[0].summary


def test_bad_arguments_are_answered_not_raised():
    bad = ToolCall(id="c", name="read_file", arguments={}, raw_arguments="{oops", error="arguments are not valid JSON")
    client = ScriptedClient([reply(bad)])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)
    assert "Could not read the arguments" in result.steps[0].summary


def test_a_tool_that_raises_becomes_an_io_error_not_a_crash():
    def exploding(**_):
        raise RuntimeError("docker died")

    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": exploding}, max_steps=1)
    assert result.steps[0].failure_category == str(FailureCategory.IO_ERROR)
    assert "docker died" in result.steps[0].summary


def test_wrong_argument_names_are_blamed_on_the_model():
    client = ScriptedClient([reply(call("read_file", filename="a.py"))])
    result, _ = episode(client, {"read_file": lambda path: ok_tool()}, max_steps=1)
    assert result.steps[0].failure_category == str(FailureCategory.INVALID_ARGUMENT)
    assert "does not accept these arguments" in result.steps[0].summary


def test_context_overflow_trims_harder_before_giving_up():
    client = ScriptedClient([], raises=ContextOverflow("too long"))
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=10, keep_full_observations=5)
    assert result.stop_reason == StopReason.CONTEXT_OVERFLOW
    assert client.calls == 2, "先裁到只留最近一条再试一次，仍然不行才放弃"


def test_a_dead_model_ends_the_instance_but_carries_the_reason():
    client = ScriptedClient([], raises=ModelUnavailable("relay unreachable"))
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=10)
    assert result.stop_reason == StopReason.API_ERROR
    assert "relay unreachable" in result.error


# ------------------------------------------------------------------ 上下文裁剪

def test_trim_messages_keeps_the_last_k_observations_in_full():
    messages = [{"role": "system", "content": "s"}]
    for i in range(4):
        messages.append({"role": "assistant", "content": "", "tool_calls": []})
        messages.append({"role": "tool", "tool_call_id": f"c{i}",
                         "content": f"<summary>\nstep {i}\n</summary>\n<content>\nbody {i}\n</content>"})

    trimmed = trim_messages(messages, keep_full=2)
    assert "body 0" not in trimmed[2]["content"] and "step 0" in trimmed[2]["content"]
    assert "body 3" in trimmed[-1]["content"]
    # 消息条数不能变：每个 tool_call 都必须留着它的回复
    assert len(trimmed) == len(messages)
    assert [m["role"] for m in trimmed] == [m["role"] for m in messages]


def test_trim_messages_with_keep_full_zero_elides_everything():
    messages = [{"role": "tool", "tool_call_id": "c", "content": "<summary>\nonly\n</summary>\n<content>\nbody\n</content>"}]
    trimmed = trim_messages(messages, keep_full=0)
    assert "body" not in trimmed[0]["content"] and "only" in trimmed[0]["content"]
    with pytest.raises(ValueError):
        trim_messages(messages, keep_full=-1)


def test_the_run_tests_hint_reaches_the_schema_the_model_sees():
    schemas = build_tool_schemas("Name a dotted test module, e.g. 'forms_tests.tests'.")
    run_tests_schema = next(s for s in schemas if s["function"]["name"] == "run_tests")
    assert "dotted test module" in run_tests_schema["function"]["description"]
    assert "dotted test module" in run_tests_schema["function"]["parameters"]["properties"]["target"]["description"]
    assert {s["function"]["name"] for s in schemas} == {
        "list_files", "search_code", "read_file", "apply_patch", "run_tests", "run_python", "git_diff", "finish",
    }


# ------------------------------------------------------------------ 落盘的读数

def test_cache_readings_reach_the_step_record():
    """缓存/推理三列要一路走到 StepRecord —— `run.py` 是 `asdict(step)` 落盘的，到这儿就等于到了 traj（决定 C20）。"""
    client = ScriptedClient([ModelReply(
        content="thinking", tool_calls=[call("read_file", path="a.py")], returned_model="fake",
        prompt_tokens=1434, completion_tokens=42,
        cache_hit_tokens=1280, cache_miss_tokens=154, reasoning_tokens=17,
    )])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)

    step = result.steps[0]
    assert (step.cache_hit_tokens, step.cache_miss_tokens, step.reasoning_tokens) == (1280, 154, 17)
    assert asdict(step)["cache_hit_tokens"] == 1280  # 落盘走的就是 asdict


def test_a_reply_without_cache_readings_records_none():
    """假客户端不给这三列时落 None，不落 0 —— 「没读到」不许伪装成「没命中」。"""
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)

    step = result.steps[0]
    assert (step.cache_hit_tokens, step.cache_miss_tokens, step.reasoning_tokens) == (None, None, None)


def test_reasoning_content_reaches_the_step_record():
    """reasoning_content 同样要一路走到 StepRecord（决定 C21）。

    这里刻意把 content 设成空串：带 tool_calls 的轮**真实形态就是这样**
    【原文 scripts/c21_reasoning_probe.py 2026-09-20 实测】，thought 那一列因此是空的。
    """
    client = ScriptedClient([ModelReply(
        content="", tool_calls=[call("read_file", path="a.py")], returned_model="fake",
        reasoning_tokens=55, reasoning_content="I should read a.py first.",
    )])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)

    step = result.steps[0]
    assert step.thought == ""  # 光看这一列会以为模型什么都没想
    assert step.reasoning_content == "I should read a.py first."
    assert asdict(step)["reasoning_content"] == "I should read a.py first."  # 落盘走的就是 asdict


def test_a_reply_without_reasoning_content_records_none():
    """不给这一列时落 None，不落 "" —— 同 C20 的 0 vs None，空串是「想了但没写」的真读数。"""
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)

    assert result.steps[0].reasoning_content is None


def test_reasoning_content_is_never_sent_back_to_the_model():
    """DeepSeek 不收回传的 reasoning_content，塞回去是 400。

    loop 构造 assistant 历史时**逐字段**取 content 与 tool_calls，新加的列不会漏进去。
    这条守的就是那个性质 —— 免得哪天有人图省事改成把整个 reply 塞回历史（决定 C21）。
    """
    secret = "MUST-NOT-BE-SENT-BACK"
    client = ScriptedClient([ModelReply(
        content="", tool_calls=[call("read_file", path="a.py")], returned_model="fake",
        reasoning_content=secret,
    )])
    episode(client, {"read_file": ok_tool}, max_steps=2)

    assert client.calls >= 2, "要有第二轮，才看得到第一轮的 assistant 消息有没有进历史"
    sent = json.dumps(client.seen[-1], ensure_ascii=False)
    assert secret not in sent
