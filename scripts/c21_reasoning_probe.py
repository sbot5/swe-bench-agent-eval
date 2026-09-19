"""C21 探针：DeepSeek 带 tools 时会不会返回 reasoning_content，litellm 透不透得出来。

㉛ 的教训（㉖ 那次就是这么踩的）：探针只走裸 HTTP，就只证了「API 会返回」，
没证「litellm 透不透出来」，结论比证据强。所以这次把链条拆成四环，每环单独出读数：

  环1  provider 原始 JSON 的 message 里有没有 reasoning_content 键   -> 裸 HTTP，不经过 litellm
  环2  litellm 的 Message 上属性在不在、值等不等于环1                 -> litellm.completion
  环3  没有 reasoning 时是「属性缺失」还是 None                       -> hasattr 负对照
  环4  它是 provider 给的，还是 litellm 从 content 里 <think> 剥出来的 -> 环1 有键即证

**带 tools 与不带 tools 各跑一组**：有的供应商在 function calling 模式下不返回 reasoning，
而我方管线每一次调用都带 tools（model.py:51-58），只测不带 tools 的那组等于没测。

离线已证的三环（$0，看 litellm 1.100 源码，不必重跑）：
  - litellm_core_utils/prompt_templates/common_utils.py:1715 —— message dict 里有
    reasoning_content 键就**原样返回**；没有才退到 <think> 解析（_parse_content_for_reasoning）
  - litellm_core_utils/llm_response_utils/convert_dict_to_response.py:671,688 —— 提取后
    传进 Message(reasoning_content=...)
  - types/utils.py:1253 Message.__init__ —— 非 None 才 setattr，**None 时 del self.reasoning_content**
    所以负对照下是「属性缺失」，getattr(msg, "reasoning_content", None) 才是对的读法

成本：4 次极小调用，合计几百 token 量级。用法：
  source ~/env.sh && cd ~/swe-bench-eval && PYTHONPATH=. .venv/bin/python scripts/c21_reasoning_probe.py
"""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

RAW_MODEL = "deepseek-flash"              # 发给 provider 的名字
LITELLM_MODEL = "openai/deepseek-flash"   # 我方 --model 写的名字（openai/ 是 provider 前缀）
PROMPT = "What is 17 * 23? Reply with just the number."
MAX_TOKENS = 200

TOOLS = [{
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "Evaluate an arithmetic expression.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
}]


def preview(text, limit=160):
    """只看头尾，reasoning 可能很长 —— 落盘体量正是本次要估的东西之一。"""
    if text is None:
        return "None"
    text = text.replace("\n", "\\n")
    if len(text) <= limit:
        return repr(text)
    return f"{text[:limit]!r}... (共 {len(text)} 字符)"


def ring1_raw_http(with_tools):
    """环1：provider 原始 JSON。绕开 litellm，证「API 到底给不给」。"""
    base = os.environ["OPENAI_BASE_URL"].rstrip("/")
    body = {
        "model": RAW_MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAX_TOKENS,
    }
    if with_tools:
        body["tools"] = TOOLS
        body["tool_choice"] = "auto"

    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def ring2_litellm(with_tools):
    """环2：走我方管线真正用的那条路 —— litellm.completion，参数与 model.py:51-58 同形。"""
    import litellm
    litellm.drop_params = True
    kwargs = {
        "model": LITELLM_MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
        "timeout": 180,
    }
    if with_tools:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"
    return litellm.completion(**kwargs)


def report(with_tools):
    label = "带 tools（真实管线形态）" if with_tools else "不带 tools（对照）"
    print(f"\n{'=' * 72}\n## {label}\n{'=' * 72}")

    # ---- 环1 ----
    print("\n[环1] provider 原始 JSON（裸 HTTP，不经 litellm）")
    raw_msg = None
    try:
        raw = ring1_raw_http(with_tools)
        raw_msg = raw["choices"][0]["message"]
        print(f"  message 的键: {sorted(raw_msg.keys())}")
        print(f"  'reasoning_content' in message: {'reasoning_content' in raw_msg}")
        print(f"  reasoning_content = {preview(raw_msg.get('reasoning_content'))}")
        print(f"  content            = {preview(raw_msg.get('content'))}")
        print(f"  tool_calls 条数     = {len(raw_msg.get('tool_calls') or [])}")
        usage = raw.get("usage") or {}
        print(f"  usage.completion_tokens_details = {usage.get('completion_tokens_details')}")
        print(f"  usage 全键: {sorted(usage.keys())}")
    except urllib.error.HTTPError as exc:
        print(f"  HTTPError {exc.code}: {exc.read()[:300]!r}")
    except Exception as exc:
        print(f"  {type(exc).__name__}: {exc}")

    # ---- 环2 / 环3 ----
    print("\n[环2] litellm.completion 透出来了吗")
    try:
        resp = ring2_litellm(with_tools)
        msg = resp.choices[0].message
        present = hasattr(msg, "reasoning_content")
        # 环3 的判别就在这里：缺失 与 None 是两回事，getattr 的默认值必须自己给
        print(f"  hasattr(message, 'reasoning_content') = {present}   <- 环3 负对照看这一行")
        print(f"  getattr(..., default='<ABSENT>')      = "
              f"{preview(getattr(msg, 'reasoning_content', '<ABSENT>'))}")
        print(f"  message.model_dump() 的键: {sorted(msg.model_dump().keys())}")
        print(f"  content    = {preview(msg.content)}")
        print(f"  tool_calls = {len(msg.tool_calls or [])} 条")
        print(f"  response.model（returned_model 那一列）= {getattr(resp, 'model', None)!r}")

        usage = getattr(resp, "usage", None)
        details = getattr(usage, "completion_tokens_details", None)
        print(f"  usage.completion_tokens                = {getattr(usage, 'completion_tokens', None)}")
        print(f"  usage.completion_tokens_details        = {details}")
        print(f"  ...reasoning_tokens（㉖ 已落盘的那列）  = "
              f"{getattr(details, 'reasoning_tokens', '<ABSENT>')}")

        # ---- 环4 ----
        print("\n[环4] 是 provider 给的，还是 litellm 从 content 里剥的")
        if raw_msg is not None:
            if "reasoning_content" in raw_msg:
                print("  环1 的原始 JSON 里**有这个键** -> provider 直接给的，"
                      "没走 _parse_content_for_reasoning 那条 <think> 解析分支")
            else:
                print("  环1 的原始 JSON 里**没有这个键**；若环2 仍读到值，"
                      "那就是 litellm 从 content 的 <think> 里剥的 —— 口径不同，要在 DESIGN 里写明")
            print(f"  裸 HTTP 的 content 含 '<think>': "
                  f"{'<think>' in (raw_msg.get('content') or '')}")
        else:
            print("  环1 没跑成，无法判别（不要拿环2 的读数替它作证）")
    except Exception as exc:
        print(f"  {type(exc).__name__}: {exc}")


def main():
    host = urlparse(os.environ["OPENAI_BASE_URL"]).netloc
    print(f"端点 host = {host}   模型 = {RAW_MODEL} / {LITELLM_MODEL}")
    print("（key 不打印）")
    for with_tools in (True, False):
        report(with_tools)


if __name__ == "__main__":
    main()
