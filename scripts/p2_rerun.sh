#!/bin/bash
# P2 原样重跑（run-id p2-rerun）：dev 25 条，照抄 p2_run.sh，只换 run-id 与 watcher 文件名。2026-09-19。
# 与 P2（p2-mine）的唯一代码差异：㉖ 的落盘三列（agent/loop.py + agent/model.py，只改响应解析，请求一字未动）；
# system prompt 指纹同为 bdf7e67c，实例集相同 —— 跑前探针见 scripts/p2_rerun_preflight.sh。
# 目的两个：P2 的第二个样本（⑦⑨ 的方差）· ㉖ 三列的第一次直读数。
# 评测命令照 EVAL-P2.md 的原样接在后面（$0，本地 docker）。
set -u

source ~/env.sh
cd ~/swe-bench-eval

echo "run-id=p2-rerun model=openai/deepseek-flash max-steps=40 workers=4 instances=subset_ids.txt(25)"

# watcher：4 个 worker 逐个抓 NetworkMode，证明不是只有一个容器断了网
( : > ~/p2_rerun_inspect.txt
  for i in $(seq 1 900); do
    for c in $(docker ps --filter name=swebench-agent- --format '{{.Names}}'); do
      grep -q "/$c " ~/p2_rerun_inspect.txt 2>/dev/null && continue
      docker inspect -f '{{.Name}} NetworkMode={{.HostConfig.NetworkMode}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" >> ~/p2_rerun_inspect.txt 2>&1
    done
    sleep 2
  done ) &
WATCHER=$!

echo "跑前余额: $(bash ~/s5_balance.sh)"
date +"start %F %T"

PYTHONPATH=. .venv/bin/python -m agent.run \
  --run-id p2-rerun \
  --workers 4 \
  --model openai/deepseek-flash
rc=$?

date +"end %F %T"
kill $WATCHER 2>/dev/null
echo "退出码: $rc"
echo "跑后余额(立刻): $(bash ~/s5_balance.sh)"
echo "=== 容器网络设置（去重）==="
sort -u ~/p2_rerun_inspect.txt
echo "=== 共 $(sort -u ~/p2_rerun_inspect.txt | wc -l) 个容器，NetworkMode=none $(grep -c 'NetworkMode=none' ~/p2_rerun_inspect.txt) 条 ==="
echo "=== 逐条读数 ==="
PYTHONPATH=. .venv/bin/python scripts/p2_rerun_check.py p2-rerun

echo "=== 评测 ==="
date +"eval start %F %T"
.venv/bin/swebench eval verified -p results/inference/p2-rerun/preds.json --run-id p2-rerun -j 6
echo "评测退出码: $?"
date +"eval end %F %T"
echo "评测后余额: $(bash ~/s5_balance.sh)"
