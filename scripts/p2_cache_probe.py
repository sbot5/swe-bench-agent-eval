"""缓存探针：同一长前缀连发两次，看 prompt_cache_hit_tokens 是否 >0。
证的是「DeepSeek 前缀缓存在这个账号/端点上确实生效」，不是回溯 S5。成本约 ¥0.001。
"""
import os, json, urllib.request

key = os.environ["OPENAI_API_KEY"]
base = os.environ["OPENAI_BASE_URL"]
prefix = ("You are a software engineering agent. " * 200)   # 约 1.4k token 的稳定前缀

def call(tag, suffix):
    body = json.dumps({
        "model": "deepseek-flash",
        "messages": [{"role": "system", "content": prefix},
                     {"role": "user", "content": suffix}],
        "max_tokens": 1,
    }).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    u = json.load(urllib.request.urlopen(req))["usage"]
    print(f"  {tag}: prompt={u['prompt_tokens']:5d}  hit={u.get('prompt_cache_hit_tokens')}  "
          f"miss={u.get('prompt_cache_miss_tokens')}")

print("同一前缀连发两次：")
call("第 1 次（冷）", "Say ok.")
call("第 2 次（同前缀）", "Say ok.")
call("第 3 次（同前缀、换后缀）", "Say fine.")
