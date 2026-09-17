#!/bin/bash
# P1 冒烟：1 条真实例跑断网配置，并在跑的过程中 docker inspect 坐实 NetworkMode=none。
# 选 django__django-11138 —— 配对对读里抄 pull/11138.patch 最明目张胆的那条。2026-09-17。
set -u

source ~/env.sh
export MSWEA_COST_TRACKING=ignore_errors
cd ~/swe-bench-eval

# 镜像齐不齐（--network=none 不影响 daemon 拉镜像，但本地齐了就不会中途卡住）
have=$(docker images --format '{{.Repository}}' | grep -c sweb.eval)
echo "本地 sweb.eval 镜像: $have"

# watcher：等 minisweagent-* 容器出现，抓 NetworkMode 落盘
( for i in $(seq 1 120); do
    cid=$(docker ps --filter 'name=minisweagent-' --format '{{.Names}}' | head -1)
    if [ -n "$cid" ]; then
      docker inspect -f '{{.Name}} NetworkMode={{.HostConfig.NetworkMode}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}IP={{range .NetworkSettings.Networks}}[{{.IPAddress}}]{{end}}' "$cid" > ~/nonet_inspect.txt 2>&1
      break
    fi
    sleep 1
  done ) &

echo "跑前余额: $(bash ~/s5_balance.sh)"
date +"start %F %T"

.venv/bin/mini-extra swebench \
  --subset verified --split test \
  --filter '^django__django-11138$' \
  -o results/inference/s5-nonet-smoke \
  -w 1 \
  -m openai/deepseek-flash \
  -c scripts/swebench-nonet.yaml -c agent.step_limit=40

rc=$?
date +"end %F %T"
echo "mini 退出码: $rc"
echo "跑后余额: $(bash ~/s5_balance.sh)"
echo "=== docker inspect 抓到的网络设置 ==="
cat ~/nonet_inspect.txt 2>/dev/null || echo "(watcher 没抓到)"
