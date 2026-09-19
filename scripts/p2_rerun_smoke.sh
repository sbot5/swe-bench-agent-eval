#!/bin/bash
# P2 原样重跑的冒烟：照抄 p2_smoke.sh，只换 run-id 与 watcher 文件名。2026-09-19。
# 选 subset 第一条 sphinx-doc__sphinx-9698（与 P2 冒烟同一条）。
# 除了验链路，还要验 ㉖ 三列在真 API 下是不是非 None —— 读不到的话这次重跑的一半目的就落空，要在花 ¥11 之前知道。
set -u

source ~/env.sh
cd ~/swe-bench-eval

( : > ~/p2_rerun_smoke_inspect.txt
  for i in $(seq 1 300); do
    for c in $(docker ps --filter name=swebench-agent- --format '{{.Names}}'); do
      grep -q "/$c " ~/p2_rerun_smoke_inspect.txt 2>/dev/null && continue
      docker inspect -f '{{.Name}} NetworkMode={{.HostConfig.NetworkMode}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" >> ~/p2_rerun_smoke_inspect.txt 2>&1
    done
    sleep 1
  done ) &
WATCHER=$!

echo "跑前余额: $(bash ~/s5_balance.sh)"
date +"start %F %T"

PYTHONPATH=. .venv/bin/python -m agent.run \
  --run-id p2-rerun-smoke \
  --limit 1 \
  --workers 1 \
  --model openai/deepseek-flash
rc=$?

date +"end %F %T"
kill $WATCHER 2>/dev/null
echo "退出码: $rc"
echo "跑后余额: $(bash ~/s5_balance.sh)"
echo "=== 容器网络设置 ==="
sort -u ~/p2_rerun_smoke_inspect.txt 2>/dev/null || echo "(watcher 没抓到)"
echo "=== 逐条读数 ==="
PYTHONPATH=. .venv/bin/python scripts/p2_rerun_check.py p2-rerun-smoke
