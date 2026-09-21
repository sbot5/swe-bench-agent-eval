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
        self.seen_tools: list[list[str]] = []

    def complete(self, messages, tools):
        self.seen.append(list(messages))
        self.seen_tools.append([schema["function"]["name"] for schema in tools])
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


def episode(client, tools, *, tool_policy=None, **config_kwargs):
    return run_episode(
        instance_id="x__x-1", problem_statement="an issue", tools=tools, client=client,
        tool_schemas=build_tool_schemas(), config=LoopConfig(**config_kwargs),
        tool_policy=tool_policy,
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


# ------------------------------------------------------------------ C22：api_finish_reason

def test_api_finish_reason_reaches_the_step_record():
    """供应商说的停止原因要一路走到 StepRecord —— 否则「参数是不是被砍了半截」永远查不了。"""
    client = ScriptedClient([ModelReply(
        content="", tool_calls=[call("read_file", path="a.py")], returned_model="fake",
        api_finish_reason="length",
    )])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)

    step = result.steps[0]
    assert step.api_finish_reason == "length"
    assert asdict(step)["api_finish_reason"] == "length"  # 落盘走的就是 asdict


def test_a_reply_without_api_finish_reason_records_none():
    """不给这一列时落 None，不落 "" —— 口径同 C20/C21。"""
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=1)

    assert result.steps[0].api_finish_reason is None


def test_api_finish_reason_does_not_collide_with_the_finish_tool_reason():
    """两个 finish_reason 同名不同义，必须各落各的（决定 C22）。

    EpisodeResult.finish_reason = 模型调 finish 工具时**自己写的理由**，整条实例一个；
    StepRecord.api_finish_reason = **供应商**说这一轮为什么停，每轮一个。
    这条测试就是防止以后有人把它们合并成一列。
    """
    client = ScriptedClient([
        ModelReply(content="", tool_calls=[call("read_file", path="a.py")],
                   returned_model="fake", api_finish_reason="length"),
        ModelReply(content="", tool_calls=[call("finish", reason="patch applied")],
                   returned_model="fake", api_finish_reason="tool_calls"),
    ])
    result, _ = episode(client, {"read_file": ok_tool}, max_steps=4)

    assert result.stop_reason == StopReason.FINISHED
    assert result.finish_reason == "patch applied"
    assert result.steps[0].api_finish_reason == "length"


# ------------------------------------------------------- 工具集每步可变（决定 C23）

ALL_TOOLS = {"read_file": ok_tool, "run_tests": ok_tool}


def drop_run_tests_from(step: int):
    """一个最小的策略：到第 `step` 步就把 run_tests 摘掉。真策略长什么样是另一回事，这里只测机制。"""
    def policy(index, _result):
        names = ["read_file", "run_tests", "finish"]
        return [name for name in names if not (index >= step and name == "run_tests")]
    return policy


def test_without_a_policy_the_tool_table_never_changes():
    """不传 tool_policy 时必须一字不差走老路：工具表每步相同、transcript 里不多一条消息、那一列记 None。"""
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, messages = episode(client, ALL_TOOLS, max_steps=3)

    assert client.seen_tools[0] == client.seen_tools[-1]
    assert "run_tests" in client.seen_tools[-1]
    assert not [m for m in messages if "<tools_changed>" in str(m.get("content", ""))]
    assert all(step.tools_declared is None for step in result.steps)


def test_a_policy_narrows_the_tool_table_from_the_step_it_fires():
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    _, messages = episode(client, ALL_TOOLS, max_steps=3, tool_policy=drop_run_tests_from(2))

    assert "run_tests" in client.seen_tools[0]          # 第 1 步还在
    assert "run_tests" not in client.seen_tools[1]      # 第 2 步起没了
    assert "read_file" in client.seen_tools[1] and "finish" in client.seen_tools[1]
    # 摘掉这件事必须落进 transcript，否则重放时看不出模型当时能调什么
    changed = [m for m in messages if "<tools_changed>" in str(m.get("content", ""))]
    assert len(changed) == 1
    assert changed[0]["role"] == "system"
    assert "no longer available: run_tests" in changed[0]["content"]


def test_the_tool_table_keeps_its_original_order_when_narrowed():
    """顺序变一遍等于请求前缀变一遍，白丢缓存（决定 C23）。"""
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    episode(client, ALL_TOOLS, max_steps=2, tool_policy=drop_run_tests_from(2))

    full_order = [name for name in client.seen_tools[0] if name != "run_tests"]
    assert client.seen_tools[1] == full_order


def test_a_retired_tool_can_no_longer_be_executed():
    """声明集和执行集必须同时收窄 —— 只改工具表、还照跑，等于没摘。"""
    ran = []

    def counting_tool(**_):
        ran.append("run_tests")
        return Observation.ok(summary="ran", content="")

    client = ScriptedClient([reply(call("run_tests", target="t.py"))])
    result, _ = episode(client, {"read_file": ok_tool, "run_tests": counting_tool},
                        max_steps=2, tool_policy=drop_run_tests_from(2))

    assert ran == ["run_tests"]  # 第 1 步真跑了，第 2 步被拦下
    retired_step = result.steps[1]
    assert retired_step.status == "error"
    assert "no longer available" in retired_step.summary
    assert retired_step.failure_category == str(FailureCategory.INVALID_ARGUMENT)


def test_each_step_records_what_it_declared():
    """重放要能精确重建当时模型看见的工具（决定 C23）。"""
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    result, _ = episode(client, ALL_TOOLS, max_steps=3, tool_policy=drop_run_tests_from(3))

    assert result.steps[0].tools_declared == ["read_file", "run_tests", "finish"]
    assert result.steps[2].tools_declared == ["read_file", "finish"]
    assert json.loads(json.dumps(asdict(result.steps[2])))["tools_declared"] == ["read_file", "finish"]


def test_putting_a_tool_back_is_announced_too():
    client = ScriptedClient([reply(call("read_file", path="a.py"))])

    def policy(index, _result):
        if index == 2:
            return ["read_file", "finish"]
        return ["read_file", "run_tests", "finish"]

    _, messages = episode(client, ALL_TOOLS, max_steps=3, tool_policy=policy)

    changed = [m["content"] for m in messages if "<tools_changed>" in str(m.get("content", ""))]
    assert len(changed) == 2
    assert "no longer available: run_tests" in changed[0]
    assert "now available: run_tests" in changed[1]


def test_a_policy_that_drops_finish_is_a_configuration_error():
    """摘掉 finish 就只剩 max_steps 能停 —— 当场炸掉，别跑完一整批才发现。"""
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    with pytest.raises(ValueError, match="finish"):
        episode(client, ALL_TOOLS, max_steps=2, tool_policy=lambda *_: ["read_file"])


def test_a_policy_cannot_declare_a_tool_that_is_not_wired_up():
    client = ScriptedClient([reply(call("read_file", path="a.py"))])
    with pytest.raises(ValueError, match="not wired up"):
        episode(client, ALL_TOOLS, max_steps=2, tool_policy=lambda *_: ["read_file", "teleport", "finish"])


# --------------------------------------------------- 批量折叠：缓存友好的裁剪（决定 C24）

def observation_message(index):
    return {"role": "tool", "tool_call_id": f"c{index}",
            "content": f"<summary>\nread file {index}\n</summary>\n<content>\nbody {index}\n</content>"}


def views_after_each_turn(fold_batch, turns=20, keep_full=5):
    """把「每轮发出去的那份视图」逐轮攒起来 —— 和 loop.py 的调用点同构。"""
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "issue"}]
    views = []
    for index in range(turns):
        messages.append({"role": "assistant", "content": f"turn {index}"})
        messages.append(observation_message(index))
        views.append(trim_messages(messages, keep_full, fold_batch))
    return views


def is_prefix(shorter, longer):
    return len(shorter) <= len(longer) and all(a == b for a, b in zip(shorter, longer))


def test_fold_batch_one_is_exactly_the_old_behaviour():
    """默认值是 1，而 1 必须逐字节等于 09-21 之前那版 —— 否则所有历史读数的口径就断了。"""
    messages = [{"role": "system", "content": "sys"}] + [observation_message(i) for i in range(9)]

    trimmed = trim_messages(messages, keep_full=5)  # 不传 fold_batch
    kept = [m["content"] for m in trimmed
            if m.get("role") == "tool" and not m["content"].startswith("[observation elided")]

    assert kept == [observation_message(i)["content"] for i in range(4, 9)]


def test_the_fold_boundary_only_moves_every_fold_batch_observations():
    """9 条观察时还没跨过第一个批次边界，10 条时才折叠 —— 折叠一次就折 5 条。"""
    nine = [{"role": "system", "content": "sys"}] + [observation_message(i) for i in range(9)]
    ten = nine + [observation_message(9)]

    elided_at_nine = [m for m in trim_messages(nine, 5, 5) if m["content"].startswith("[observation elided")]
    elided_at_ten = [m for m in trim_messages(ten, 5, 5) if m["content"].startswith("[observation elided")]

    assert elided_at_nine == []   # 保护窗口浮到了 9 条，模型看到的只多不少
    assert len(elided_at_ten) == 5


def test_batched_folding_breaks_the_prefix_far_less_often():
    """缓存友好的形式判据：折叠边界不动的那几轮，上一轮的视图必须是下一轮视图的**前缀**。

    这正是 EVAL-P2-rerun.md §4.2 实测到的那件事 —— 前缀一断，其后全部未命中，而未命中贵 50 倍。
    ⚠️ 这三个数字是 20 轮 / keep_full=5 下的快照，机制本身由下一条不变量测试钉死。
    """
    def breaks(fold_batch):
        views = views_after_each_turn(fold_batch)
        return sum(1 for a, b in zip(views, views[1:]) if not is_prefix(a, b))

    assert breaks(1) == 15   # 现状：过了保护窗口之后每轮都断
    assert breaks(5) == 3    # 攒 5 条：20 轮只断 3 次
    assert breaks(10) == 1


@pytest.mark.parametrize("keep_full", [1, 3, 5])
@pytest.mark.parametrize("fold_batch", [1, 2, 5, 7])
def test_the_prefix_breaks_exactly_when_the_fold_boundary_moves(keep_full, fold_batch):
    """真正要钉的不变量：**前缀断裂 ⟺ 折叠边界移动**，对任意 (keep_full, fold_batch) 都成立。

    上一条只记录了三个计数，改坏公式而恰好保住那三个数字仍能混过去；这一条把两件独立可观察的事
    绑在一起，公式错了就对不上（Codex 09-21 审稿 MINOR）。
    """
    views = views_after_each_turn(fold_batch, turns=16, keep_full=keep_full)
    folded = [sum(1 for m in view if m["content"].startswith("[observation elided")) for view in views]

    broke = [not is_prefix(a, b) for a, b in zip(views, views[1:])]
    moved = [before != after for before, after in zip(folded, folded[1:])]
    assert broke == moved


@pytest.mark.parametrize("keep_full", [1, 3, 5])
@pytest.mark.parametrize("fold_batch", [1, 2, 5, 7])
def test_the_protected_window_stays_between_keep_full_and_keep_full_plus_batch(keep_full, fold_batch):
    """浮动窗口的两头都要有闸：下界是「模型看到的只多不少」，上界是「不会攒到装不下」。"""
    for turns in range(1, 17):
        view = views_after_each_turn(fold_batch, turns=turns, keep_full=keep_full)[-1]
        full = sum(1 for m in view
                   if m.get("role") == "tool" and not m["content"].startswith("[observation elided"))
        assert min(turns, keep_full) <= full <= keep_full + fold_batch - 1 or full == turns


def test_batching_never_shows_the_model_less_than_keep_full():
    """浮动窗口只会更宽不会更窄 —— 这条保证「省钱的改动不会顺手削弱模型」。"""
    for turns in range(1, 21):
        views = views_after_each_turn(5, turns=turns)
        full = [m for m in views[-1]
                if m.get("role") == "tool" and not m["content"].startswith("[observation elided")]
        assert len(full) >= min(turns, 5)


def test_a_fold_batch_below_one_is_rejected():
    with pytest.raises(ValueError, match="fold_batch"):
        trim_messages([], keep_full=5, fold_batch=0)


def test_context_overflow_also_turns_batching_off():
    """装不下的时候缓存不重要了：keep_full 和 fold_batch 一起降到最狠的一档（决定 C11 + C24）。"""
    class OverflowOnce:
        def __init__(self):
            self.calls = 0
            self.seen = []

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                raise ContextOverflow("too long")
            self.seen.append(list(messages))
            return reply(call("finish", reason="done"))

    client = OverflowOnce()
    result, _ = episode(client, ALL_TOOLS, max_steps=4)

    assert result.stop_reason == StopReason.FINISHED
    assert client.calls == 2


def test_overflow_never_widens_a_zero_keep_full_window():
    """`keep_full=0` 比 1 更狠，降档**不许把它放宽**（Codex 09-21 审稿 MAJOR-2）。

    原来的降档直接赋 `keep_full = 1`：配成 0 的跑一旦 overflow，重试发出去的历史反而更长。
    """
    class OverflowAtThirdCall:
        def __init__(self):
            self.calls = 0
            self.seen = []

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 3:
                raise ContextOverflow("too long")
            self.seen.append(list(messages))
            if self.calls > 3:
                return reply(call("finish", reason="done"))
            return reply(call("read_file", path=f"a{self.calls}.py"))

    client = OverflowAtThirdCall()
    result, _ = episode(client, ALL_TOOLS, max_steps=6, keep_full_observations=0, fold_batch=5)

    assert result.stop_reason == StopReason.FINISHED
    full_after_overflow = [m for m in client.seen[-1] if m.get("role") == "tool"
                           and not m["content"].startswith("[observation elided")]
    assert full_after_overflow == []
