#!/bin/bash
# A 组 reasoning 对读：A 组 8 条 + 对照 2 条，跑两遍。2026-09-20（周日，北京空闲价）。
#
# 判据**跑前锁定**在 docs/EVAL-A-reasoning.md §一，git 时间戳即证据（⑭）。
# 与 p3-r1/p3-r2 的唯一差异是 C21 仪器（reasoning_content 落盘），agent/ 一行未动
# （scripts/areason_preflight.py 验）→ 本跑**同时是 P3 配置的第 3、4 个样本**，
# 与「P2 → P2 原样重跑」同型。
#
# 要买的读数：【未知】②「模型凭什么认为自己还没复现完」。
# 跑两遍是因为⑦⑨：同配置单次跑的 resolved 有 ±3 的方差，动手数才是稳定量。
#
# 跑法：wsl -d swebench -e bash -lc 'bash /home/zixu/swe-bench-eval/scripts/areason_run.sh'
set -u

source ~/env.sh
cd ~/swe-bench-eval

run_one () {
  RID=$1
  echo "=============================== $RID ==============================="
  echo "run-id=$RID model=openai/deepseek-flash max-steps=40 workers=4 instances=groupa_ids.txt(10)"

  # watcher：逐个抓 NetworkMode，证明不是只有一个容器断了网（P1 立的规矩）
  ( : > ~/${RID}_inspect.txt
    for i in $(seq 1 900); do
      for c in $(docker ps --filter name=swebench-agent- --format '{{.Names}}'); do
        grep -q "/$c " ~/${RID}_inspect.txt 2>/dev/null && continue
        docker inspect -f '{{.Name}} NetworkMode={{.HostConfig.NetworkMode}} Networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" >> ~/${RID}_inspect.txt 2>&1
      done
      sleep 2
    done ) &
  WATCHER=$!

  echo "跑前余额: $(bash ~/s5_balance.sh)"
  TZ=Asia/Shanghai date +"start 北京 %F %T %a"

  PYTHONPATH=. .venv/bin/python -m agent.run \
    --run-id $RID \
    --instances groupa_ids.txt \
    --workers 4 \
    --model openai/deepseek-flash
  rc=$?

  TZ=Asia/Shanghai date +"end 北京 %F %T %a"
  kill $WATCHER 2>/dev/null
  echo "退出码: $rc"
  echo "跑后余额(立刻): $(bash ~/s5_balance.sh)"
  echo "=== 容器网络设置（去重）==="
  sort -u ~/${RID}_inspect.txt
  echo "=== 共 $(sort -u ~/${RID}_inspect.txt | wc -l) 个容器，NetworkMode=none $(grep -c 'NetworkMode=none' ~/${RID}_inspect.txt) 条 ==="
  echo "=== 逐条读数 ==="
  PYTHONPATH=. .venv/bin/python scripts/p2_rerun_check.py $RID

  echo "=== 评测 $RID ==="
  .venv/bin/swebench eval verified -p results/inference/$RID/preds.json --run-id $RID -j 6
  echo "评测退出码: $?"
  echo "评测后余额: $(bash ~/s5_balance.sh)"
}

run_one a-reason-r1
run_one a-reason-r2

echo "=============================== 两跑完毕 ==============================="
TZ=Asia/Shanghai date +"北京 %F %T"
echo "余额（延迟结算要等十几分钟收敛，收工前再读一次）: $(bash ~/s5_balance.sh)"
echo "=== C21 读数覆盖与选段 ==="
PYTHONPATH=. .venv/bin/python scripts/areason_read.py --stats a-reason-r1 a-reason-r2
