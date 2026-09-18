#!/bin/bash
# P2 正式跑：我方 scaffold + run_python + --network=none，dev 25 条。
# 与 S5 的唯一有意差异：agent/ 的四个文件（run_python 与 prompt 是一个复合变量，不许拆开归功）。
# --network=none 对 S5 是 no-op（六个工具本来就发不出请求），不构成变量。2026-09-18。
set -u

source ~/env.sh
cd ~/swe-bench-eval

echo "run-id=p2-mine model=openai/deepseek-flash max-steps=40 workers=4 instances=subset_ids.txt(25)"

# watcher：4 个 worker 逐个抓 NetworkMode，证明不是只有一个容器断了网
( : > ~/p2_inspect_full.txt
  for i in $(seq 1 900); do
    for c in $(docker ps --filter name=swebench-agent- --format '{{.Names}}'); do
      grep -q "/$c " ~/p2_inspect_full.txt 2>/dev/null && continue
      docker inspect -f '{{.Name}} NetworkMode={{.HostConfig.NetworkMode}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" >> ~/p2_inspect_full.txt 2>&1
    done
    sleep 2
  done ) &
WATCHER=$!

echo "跑前余额: $(bash ~/s5_balance.sh)"
date +"start %F %T"

PYTHONPATH=. .venv/bin/python -m agent.run \
  --run-id p2-mine \
  --workers 4 \
  --model openai/deepseek-flash
rc=$?

date +"end %F %T"
kill $WATCHER 2>/dev/null
echo "退出码: $rc"
echo "跑后余额(立刻): $(bash ~/s5_balance.sh)"
echo "=== 容器网络设置（去重）==="
sort -u ~/p2_inspect_full.txt
echo "=== 共 $(sort -u ~/p2_inspect_full.txt | wc -l) 个容器，NetworkMode=none $(grep -c 'NetworkMode=none' ~/p2_inspect_full.txt) 条 ==="
