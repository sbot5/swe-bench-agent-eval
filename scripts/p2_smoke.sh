#!/bin/bash
# P2 冒烟：我方 scaffold + run_python + --network=none，真模型跑 1 条。
# 选 subset 第一条 sphinx-doc__sphinx-9698（S3' 真模型基线：18 次调用 -> 1191 字符 patch）。2026-09-18。
set -u

source ~/env.sh
cd ~/swe-bench-eval

# watcher：抓我方容器的 NetworkMode，坐实 --network=none 在真跑里生效（不是只写在代码里）
( : > ~/p2_smoke_inspect.txt
  for i in $(seq 1 300); do
    for c in $(docker ps --filter name=swebench-agent- --format '{{.Names}}'); do
      grep -q "/$c " ~/p2_smoke_inspect.txt 2>/dev/null && continue
      docker inspect -f '{{.Name}} NetworkMode={{.HostConfig.NetworkMode}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" >> ~/p2_smoke_inspect.txt 2>&1
    done
    sleep 1
  done ) &
WATCHER=$!

echo "跑前余额: $(bash ~/s5_balance.sh)"
date +"start %F %T"

PYTHONPATH=. .venv/bin/python -m agent.run \
  --run-id p2-smoke \
  --limit 1 \
  --workers 1 \
  --model openai/deepseek-flash
rc=$?

date +"end %F %T"
kill $WATCHER 2>/dev/null
echo "退出码: $rc"
echo "跑后余额: $(bash ~/s5_balance.sh)"
echo "=== 容器网络设置 ==="
sort -u ~/p2_smoke_inspect.txt 2>/dev/null || echo "(watcher 没抓到)"
