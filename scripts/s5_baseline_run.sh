#!/bin/bash
# S5-baseline：mini-SWE-agent 跑同 25 条。照 docs/EVAL-S5-baseline.md §四，2026-09-17。
# 三处必改的理由全在那份文档 §三；这里只执行，不要在这儿改参数。
set -u

source ~/env.sh                             # ③ 顺序是硬要求：mini 自带 .env 仍指向被屏蔽的中转站
export MSWEA_COST_TRACKING=ignore_errors    # ② 否则第一次模型调用后抛 RuntimeError，25 条全成空 patch

cd ~/swe-bench-eval
YAML=.venv/lib/python3.12/site-packages/minisweagent/config/benchmarks/swebench.yaml

echo "run-id=s5-baseline model=openai/deepseek-flash step_limit=40 workers=4"
echo "base_url=$OPENAI_BASE_URL"
echo "跑前余额: $(bash ~/s5_balance.sh)"
date +"start %F %T"

.venv/bin/mini-extra swebench \
  --subset verified --split test \
  --filter "$(cat ~/s5_baseline_filter.txt)" \
  -o results/inference/s5-baseline \
  -w 4 \
  -m openai/deepseek-flash \
  -c "$YAML" -c agent.step_limit=40

rc=$?
date +"end %F %T"
echo "mini 退出码: $rc"
echo "跑后余额: $(bash ~/s5_balance.sh)"
