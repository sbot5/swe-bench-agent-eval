#!/bin/bash
# P4：分阶段 Round，A 组 8 条 + 2 条对照，跑两遍。2026-09-22。
#
# 与 p3 的唯一差异是多了 `--staged`：骨架 system prompt + 三段指令尾部追加 + 逐段工具表
# （agent/staged.py；指纹、切法依据、判据缺口全在 docs/EVAL-P4-staged.md §2.1）。
# 三个成分①段划分 ②段指令 ③撤能力**同属一个复合变量，不许拆开归功**（P3 ㊳ 的教训）。
#
# 判据跑前已锁定并 commit（同一份文档 §三，跑完一个字不许改，结果只往 §八 补）：
#   主判据 A 组 apply_patch>0 的实例-跑组合 >=5/16 且两跑各 >=2（固定边际精确检验单侧 p=0.00664）
#   必报反向指标「有 patch 但 unresolved」—— 空 patch 变错 patch 是失败模式换型不是提升
#   合规性（Implement 段考古率 vs Collect 段）单列为独立判据：主判据不过线时先答「有没有被遵守」（㊴）
#   对照两条只能否定不能肯定；⚠️ Collect 闸切不到这两条（自然首刀 25/38 与 None/22），误伤记【未知】
#
# ⚠️ 排北京空闲时段跑（工作日 9-12、14-18 是高峰，其余含周末半价）。两跑约 ¥5.8 空闲价。
# ⚠️ --max-steps 不传就是默认 40，正好等于切法总轮数；传别的值 --staged 会当场 parser.error。
#
# 跑法：wsl -d swebench -e bash -lc 'bash /home/zixu/swe-bench-eval/scripts/p4_run.sh'
set -u

source ~/env.sh
cd ~/swe-bench-eval

echo "=== 跑前指纹（与 docs/EVAL-P4-staged.md §2.1 抄的那串必须一致）==="
PYTHONPATH=. .venv/bin/python -m agent.staged

run_one () {
  RID=$1
  echo "=============================== $RID ==============================="
  echo "run-id=$RID model=openai/deepseek-flash max-steps=40(默认) workers=4 instances=groupa_ids.txt(10) --staged"

  # watcher：逐个抓 NetworkMode，证明不是只有一个容器断了网（P1 立的规矩，§四 第 4 条）
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
    --model openai/deepseek-flash \
    --staged
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

run_one p4-r1
run_one p4-r2

echo "=============================== 两跑完毕 ==============================="
TZ=Asia/Shanghai date +"北京 %F %T"
echo "余额（延迟结算要等十几分钟收敛，收工前再读一次）: $(bash ~/s5_balance.sh)"
