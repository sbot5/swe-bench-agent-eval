#!/bin/bash
# S5-baseline（mini 同 25 条）跑前零成本探针，2026-09-17。不调模型、不起容器、不花钱。
#
# 验两件事：
#   [1] mini-extra 启动时会 "Loading global config from ~/.config/mini-swe-agent/.env"，
#       而那个文件里还是**被校内网屏蔽的中转站** hgapi.dieqiyun.top/v1。
#       代码里有两处 load_dotenv：__init__.py:36 不带 override（现有环境变量赢），
#       run/utilities/config.py:22 带 override=True 但只在 `mini-extra config` / 交互式 `mini` 用。
#       这里实测 `source ~/env.sh` 之后 import minisweagent，OPENAI_BASE_URL 到底是谁。
#   [2] `--subset verified --split test` + 25 条 id 的 `--filter` 正则能不能正好命中 25 条。
#       mini 用 re.match（只锚开头），所以正则必须自己补 `$`，否则前缀会误命中。
set -u
source ~/env.sh
echo "[1] env.sh 导出后:            OPENAI_BASE_URL=$OPENAI_BASE_URL"
cd ~/swe-bench-eval
.venv/bin/python - <<'PY'
import os
import re

import minisweagent
from minisweagent.run.benchmarks.swebench import DATASET_MAPPING, filter_instances

print("[1] import minisweagent 之后: OPENAI_BASE_URL=", os.environ.get("OPENAI_BASE_URL"))
print("[1] mini 的全局配置文件:      ", minisweagent.global_config_file)

ids = [ln.strip() for ln in open("subset_ids.txt", encoding="utf-8") if ln.strip()]
pattern = "^(" + "|".join(re.escape(i) for i in ids) + ")$"
with open(os.path.expanduser("~/s5_baseline_filter.txt"), "w", encoding="utf-8") as fh:
    fh.write(pattern + "\n")
print("[2] subset_ids.txt 条数:      ", len(ids))

from datasets import load_dataset

ds = list(load_dataset(DATASET_MAPPING["verified"], split="test"))
hit = filter_instances(ds, filter_spec=pattern)
print("[2] verified/test 总条数:     ", len(ds))
print("[2] 正则命中:                 ", len(hit))
missing = sorted(set(ids) - {d["instance_id"] for d in hit})
print("[2] 没命中的:                 ", missing if missing else "无")
print("[2] 正则已写到 ~/s5_baseline_filter.txt，长度", len(pattern), "字符")

# [3] 生效的 API key 到底是哪一把（只印指纹，绝不印 key 本身）
import hashlib


def fp(s):
    return hashlib.md5(s.strip().encode()).hexdigest()[:8] if s else "<空>"


def key_of(path):
    try:
        for ln in open(os.path.expanduser(path), encoding="utf-8"):
            if ln.startswith("API_KEY=") or ln.startswith("OPENAI_API_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


eff = os.environ.get("OPENAI_API_KEY", "")
print("[3] 生效 key 指纹:            ", fp(eff), " 长度", len(eff))
print("[3] 中转站 .env 的 key 指纹:  ", fp(key_of("~/.config/mini-swe-agent/.env")))
print("[3] Monash .env 的 key 指纹:  ", fp(key_of("/mnt/e/dev/Monash/Career/07-swe-bench-agent/.env")))

# [4] litellm 认不认 deepseek-flash 的价格 —— 决定 mini 的 cost_limit 这层保护有没有用
import litellm

for name in ("deepseek-flash", "openai/deepseek-flash", "deepseek/deepseek-flash"):
    print("[4] litellm 价格表[", name, "] ->", litellm.model_cost.get(name, "<不认识>"))
PY

echo "[5] 官方端点现在有哪些模型:"
curl -s -H "Authorization: Bearer $OPENAI_API_KEY" "$OPENAI_BASE_URL/models" | tr ',' '\n' | grep -oE '"id"[^,]*'
