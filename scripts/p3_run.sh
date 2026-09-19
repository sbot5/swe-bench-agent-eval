#!/bin/bash
# P3：改 SYSTEM_PROMPT 的 How-to-work 第 3 + 第 5 条，A 组 8 条 + 2 条对照，跑两遍。2026-09-19。
#
# 与 p2-rerun 的唯一差异：prompt 指纹 bdf7e67c -> 019bb6fd，agent/ 其余一行未动（scripts/p3_preflight.py 验）。
# 第 3 与第 5 条是**一个复合变量，不许拆开归功**：第 5 条原文无条件要求 "Rerun your run_python script"，
# 只改第 3 条会让 prompt 自相矛盾，模型照第 5 条走还是卡在同一处。
# 第 3 条里的 "two attempts" 是本次新加的具体退出条件（交接单原话只说「复现不了」），
# 算复合变量的第三个成分，同样不许单独归功。
#
# 判据：A 组 8 条的 apply_patch 调用数。基线 = S5 / P2 / p2-rerun 三跑 24/24 次全 0。
# 对照两条（django-14631 救回 · sphinx-9711 带沟里）查「有没有把本来会动手的弄坏」。
# 跑两遍是因为⑦⑨：同配置单次跑的 resolved 有 ±3 的方差，动手数才是稳定量。
#
# 跑法：wsl -d swebench -e bash -lc 'bash /home/zixu/swe-bench-eval/scripts/p3_run.sh'
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

run_one p3-r1
run_one p3-r2

echo "=============================== 两跑完毕 ==============================="
TZ=Asia/Shanghai date +"北京 %F %T"
echo "余额（延迟结算要等十几分钟收敛，收工前再读一次）: $(bash ~/s5_balance.sh)"
