#!/bin/bash
# P1 正式跑：mini-SWE-agent 断网跑同 25 条。与 s5_baseline_run.sh 逐项对照，唯一有意改动是 run_args。
# 2026-09-17。
set -u

source ~/env.sh                             # ③ 顺序是硬要求
export MSWEA_COST_TRACKING=ignore_errors    # ② 否则第一次模型调用后抛 RuntimeError
cd ~/swe-bench-eval

echo "run-id=s5-baseline-nonet model=openai/deepseek-flash step_limit=40 workers=4 network=none"
echo "config=scripts/swebench-nonet.yaml (与 site-packages 原件只差 run_args 一行)"

# watcher：正式跑有 4 个 worker，逐个抓 NetworkMode，证明不是只有一个容器断了网
( : > ~/nonet_inspect_full.txt
  for i in $(seq 1 200); do
    for c in $(docker ps --filter 'name=minisweagent-' --format '{{.Names}}'); do
      grep -q "^/$c " ~/nonet_inspect_full.txt 2>/dev/null && continue
      docker inspect -f '{{.Name}} NetworkMode={{.HostConfig.NetworkMode}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" >> ~/nonet_inspect_full.txt 2>&1
    done
    sleep 3
  done ) &
WATCHER=$!

echo "跑前余额: $(bash ~/s5_balance.sh)"
date +"start %F %T"

.venv/bin/mini-extra swebench \
  --subset verified --split test \
  --filter "$(cat ~/s5_baseline_filter.txt)" \
  -o results/inference/s5-baseline-nonet \
  -w 4 \
  -m openai/deepseek-flash \
  -c scripts/swebench-nonet.yaml -c agent.step_limit=40

rc=$?
date +"end %F %T"
kill $WATCHER 2>/dev/null
echo "mini 退出码: $rc"
echo "跑后余额(立刻): $(bash ~/s5_balance.sh)"
echo "=== 抓到的容器网络设置（去重后）==="
sort -u ~/nonet_inspect_full.txt | head -30
echo "=== 共 $(sort -u ~/nonet_inspect_full.txt | wc -l) 个容器，NetworkMode=none 的有 $(grep -c 'NetworkMode=none' ~/nonet_inspect_full.txt) 条记录 ==="
