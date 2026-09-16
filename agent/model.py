"""模型客户端：把 litellm 的返回收敛成 loop.ModelReply，并把「可重试」和「没救了」两类错误分开。

放在单独一个模块，是为了让 loop.py 不认识任何供应商 —— 测试注入假客户端时不用装 litellm（决定 C13）。
决定、实测、已纠正的错误：docs/DESIGN-loop.md §五
"""
import random
import sys
import time
from collections.abc import Sequence
from typing import Final

import litellm

from agent.loop import ContextOverflow, ModelReply, ModelUnavailable, parse_tool_calls

DEFAULT_MODEL: Final[str] = "openai/gpt-5.6-luna"
MAX_ATTEMPTS: Final[int] = 4
BACKOFF_BASE: Final[float] = 2.0
REQUEST_TIMEOUT: Final[int] = 180

# 中转站抖动过一次（S2 实测的 ServiceUnavailableError），这几类退避重试；其余直接判死
_RETRYABLE: Final[tuple[type[Exception], ...]] = tuple(
    exc for exc in (
        getattr(litellm, name, None)
        for name in ("RateLimitError", "APIConnectionError", "ServiceUnavailableError",
                     "InternalServerError", "Timeout", "APIError")
    ) if isinstance(exc, type)
)


class LiteLLMClient:
    """按 OpenAI function calling 的协议调一次模型，返回 ModelReply。

    重试只针对连接/限流类错误，最多 MAX_ATTEMPTS 次指数退避；上下文超限单独抛 ContextOverflow
    让循环去裁历史，其余错误一律 ModelUnavailable —— 重试一个 400 只是把钱和时间烧掉（决定 C12）。
    """

    def __init__(self, model: str = DEFAULT_MODEL, *, temperature: float = 0.0,
                 max_attempts: int = MAX_ATTEMPTS, timeout: int = REQUEST_TIMEOUT) -> None:
        self.model = model
        self.temperature = temperature
        self.max_attempts = max_attempts
        self.timeout = timeout
        litellm.drop_params = True  # gpt-5.x 不吃 temperature 时丢掉参数，而不是整条请求失败

    def complete(self, messages: Sequence[dict], tools: Sequence[dict]) -> ModelReply:
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = litellm.completion(
                    model=self.model,
                    messages=list(messages),
                    tools=list(tools),
                    tool_choice="auto",
                    temperature=self.temperature,
                    timeout=self.timeout,
                )
            except litellm.ContextWindowExceededError as exc:
                raise ContextOverflow(str(exc)) from exc
            except _RETRYABLE as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                # 加抖动：整批并行时几个 worker 同时被限流，同步重试会再撞一次
                delay = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                print(f"[WARNING] {type(exc).__name__} on attempt {attempt}/{self.max_attempts}; "
                      f"retrying in {delay:.1f}s", file=sys.stderr)
                time.sleep(delay)
            except Exception as exc:  # 认证错、请求体非法等：重试不会变对
                raise ModelUnavailable(f"{type(exc).__name__}: {exc}") from exc
            else:
                return _to_reply(response)

        raise ModelUnavailable(
            f"{type(last_error).__name__} after {self.max_attempts} attempts: {last_error}"
        )


def _to_reply(response) -> ModelReply:
    """把 litellm 的响应对象收敛成 ModelReply。算不出成本时记 0 并继续，不为了一个读数中断实例。"""
    message = response.choices[0].message

    try:
        cost = float(litellm.completion_cost(completion_response=response))
    except Exception:  # 价格表里没有这个模型时 completion_cost 会抛；成本记 0 比整条实例挂掉好
        cost = 0.0

    usage = getattr(response, "usage", None)
    return ModelReply(
        content=message.content or "",
        tool_calls=parse_tool_calls(message.tool_calls or []),
        cost=cost,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        # 请求写的是 luna，返回的是什么要原样记下来 —— 执行计划 §八「中转站是否真给 luna」靠这一列查
        returned_model=getattr(response, "model", "") or "",
    )
