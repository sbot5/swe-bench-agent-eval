"""model.py 的单测：usage 那几列到底读不读得到，以及「没读到」和「读到 0」分不分得开。

不发任何请求（$0）。主路径走 litellm **自己的**响应转换器，而不是我手搓一个 usage 对象 ——
㉖ 那个坑就是「裸 HTTP 探针证明了 API 会返回，但没人验过 litellm 透不透出来」。
决定 C20：docs/DESIGN-loop.md §三。
"""
from types import SimpleNamespace

from litellm.types.utils import ModelResponse
from litellm.utils import convert_to_model_response_object

from agent.model import _first_int, _first_str, _to_reply

# DeepSeek 实际返回的 usage 形状【原文 scripts/p2_cache_probe.py 的 09-18 实测输出】
DEEPSEEK_USAGE = {
    "prompt_tokens": 1434,
    "completion_tokens": 42,
    "total_tokens": 1476,
    "prompt_cache_hit_tokens": 1280,
    "prompt_cache_miss_tokens": 154,
    "completion_tokens_details": {"reasoning_tokens": 17},
}


def response_from(usage: dict | None, model: str = "deepseek-flash", message: dict | None = None):
    """按 OpenAI 协议的原始 JSON 造一条响应，再交给 litellm 的转换器 —— 运行时走的就是这条路。

    message 留空就是原来那条最普通的回复；要测 reasoning_content 这类**消息体**上的字段时才覆盖它。
    """
    raw = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": message or {"role": "assistant", "content": "ok", "tool_calls": None}}],
    }
    if usage is not None:
        raw["usage"] = usage
    return convert_to_model_response_object(
        response_object=raw, model_response_object=ModelResponse(), stream=False
    )


def test_deepseek_usage_lands_in_reply():
    """DeepSeek 的三个读数经 litellm 转换后仍取得到 —— ㉖ 修的就是这条。"""
    reply = _to_reply(response_from(DEEPSEEK_USAGE))

    assert reply.prompt_tokens == 1434
    assert reply.completion_tokens == 42
    assert reply.cache_hit_tokens == 1280
    assert reply.cache_miss_tokens == 154
    assert reply.reasoning_tokens == 17
    assert reply.returned_model == "deepseek-flash"


def test_hit_plus_miss_equals_prompt_tokens():
    """口径自洽：hit + miss == prompt_tokens。不成立的话这三列就不能拿来算命中率。"""
    reply = _to_reply(response_from(DEEPSEEK_USAGE))

    assert reply.cache_hit_tokens + reply.cache_miss_tokens == reply.prompt_tokens


def test_provider_silent_reads_none_not_zero():
    """负对照：供应商不给这些字段时记 None。

    **这是 C20 的全部意义** —— 记成 0 的话，「没读到」和「一次没命中」在轨迹里长得一模一样，
    就是 `cost=$0.0000` 那个假读数的翻版。
    """
    reply = _to_reply(response_from({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}))

    assert reply.prompt_tokens == 10  # 这两列照旧
    assert reply.cache_hit_tokens is None
    assert reply.cache_miss_tokens is None
    assert reply.reasoning_tokens is None


def test_genuine_zero_is_kept_as_zero():
    """真零要留住：冷跑第一次调用 hit=0 是**真读数**，不许被当成「没给」。"""
    cold = dict(DEEPSEEK_USAGE, prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=1434)
    reply = _to_reply(response_from(cold))

    assert reply.cache_hit_tokens == 0
    assert reply.cache_miss_tokens == 1434


def test_normalized_field_alone_is_enough():
    """只给归一化字段、不给 DeepSeek 原名时也要读到 —— 换供应商不必再改一次代码。"""
    reply = _to_reply(response_from({
        "prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105,
        "prompt_tokens_details": {"cached_tokens": 64},
    }))

    assert reply.cache_hit_tokens == 64
    assert reply.cache_miss_tokens is None  # miss 没有归一化字段，不许凭 100-64 推一个出来


def test_missing_usage_object_does_not_crash():
    """连 usage 都没有的响应（中转站抖动时见过）不许炸掉整条实例。"""
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
        model="whatever",
    )
    reply = _to_reply(response)

    assert reply.prompt_tokens == 0
    assert reply.cache_hit_tokens is None
    assert reply.reasoning_tokens is None


def test_first_int_rejects_bool_and_non_int():
    """bool 是 int 的子类，会静默变成 1/0；字符串型读数同样不要。"""
    assert _first_int(None, 7) == 7
    assert _first_int(True, 7) == 7
    assert _first_int("1280", 1280) == 1280
    assert _first_int(None, None) is None
    assert _first_int(0, 99) == 0  # 0 是合法读数，不许被跳过


# ---- C21：reasoning_content ----

# DeepSeek **带 tools** 时的真实消息体形状【原文 scripts/c21_reasoning_probe.py 2026-09-20 实测】：
# content 是空串、tool_calls 一条，推理全在 reasoning_content 里 —— 正是 thought 空白的机制。
TOOLCALL_MESSAGE = {
    "role": "assistant",
    "content": "",
    "tool_calls": [{
        "id": "call_0",
        "type": "function",
        "function": {"name": "calculate", "arguments": '{"expression": "17*23"}'},
    }],
    "reasoning_content": "17*23 = 391.",
}


def test_reasoning_content_lands_in_reply():
    """主路径：provider 给的 reasoning_content 经 litellm 转换后仍取得到（决定 C21）。"""
    reply = _to_reply(response_from(DEEPSEEK_USAGE, message=TOOLCALL_MESSAGE))

    assert reply.reasoning_content == "17*23 = 391."


def test_reasoning_survives_empty_thought():
    """本次改动的全部理由：content 空串、推理却不空。

    thought 那一列取的是 content（loop.py），所以光读 traj 的 thought 会以为模型什么都没想 ——
    EVAL-P2-rerun.md 里 django-11138「57 步 thought 全空、38/40 轮在推理」就是这么来的。
    """
    reply = _to_reply(response_from(DEEPSEEK_USAGE, message=TOOLCALL_MESSAGE))

    assert reply.content == ""
    assert reply.tool_calls  # 确实是「带 tool_calls 的那种轮」，不是普通回复
    assert reply.reasoning_content


def test_no_reasoning_reads_none_not_empty_string():
    """负对照：provider 不给这个字段时记 None。

    litellm 在 reasoning_content is None 时会 `del self.reasoning_content`
    （litellm/types/utils.py 的 Message.__init__），所以这里验的是「属性缺失不崩、也不冒充空串」。
    ⚠️ 这一环 09-20 的四环探针**没测到** —— 两组都拿到了推理文本，负对照当时只有离线源码
    证据（㉛：证据链要逐环点名）。这条测试就是补那一环的。
    """
    reply = _to_reply(response_from(DEEPSEEK_USAGE))

    assert reply.reasoning_content is None


def test_empty_reasoning_is_kept_as_empty_string():
    """空串是真读数（这一轮没产出推理文本），不许折叠成 None —— 同 C20 的 0 vs None。"""
    message = dict(TOOLCALL_MESSAGE, reasoning_content="")
    reply = _to_reply(response_from(DEEPSEEK_USAGE, message=message))

    assert reply.reasoning_content == ""


def test_first_str_rejects_non_str():
    """口径同 _first_int：只认字符串，空串是合法读数不许跳过。"""
    assert _first_str(None, "x") == "x"
    assert _first_str(123, "x") == "x"
    assert _first_str(None, None) is None
    assert _first_str("", "later") == ""
