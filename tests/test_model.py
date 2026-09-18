"""model.py 的单测：usage 那几列到底读不读得到，以及「没读到」和「读到 0」分不分得开。

不发任何请求（$0）。主路径走 litellm **自己的**响应转换器，而不是我手搓一个 usage 对象 ——
㉖ 那个坑就是「裸 HTTP 探针证明了 API 会返回，但没人验过 litellm 透不透出来」。
决定 C20：docs/DESIGN-loop.md §三。
"""
from types import SimpleNamespace

from litellm.types.utils import ModelResponse
from litellm.utils import convert_to_model_response_object

from agent.model import _first_int, _to_reply

# DeepSeek 实际返回的 usage 形状【原文 scripts/p2_cache_probe.py 的 09-18 实测输出】
DEEPSEEK_USAGE = {
    "prompt_tokens": 1434,
    "completion_tokens": 42,
    "total_tokens": 1476,
    "prompt_cache_hit_tokens": 1280,
    "prompt_cache_miss_tokens": 154,
    "completion_tokens_details": {"reasoning_tokens": 17},
}


def response_from(usage: dict | None, model: str = "deepseek-flash"):
    """按 OpenAI 协议的原始 JSON 造一条响应，再交给 litellm 的转换器 —— 运行时走的就是这条路。"""
    raw = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "ok", "tool_calls": None}}],
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
