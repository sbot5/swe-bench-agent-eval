#!/bin/bash
# A 组 reasoning 对读的冒烟。2026-09-20。
#
# 唯一目的：**在真 API 下确认 reasoning_content 真的落到 traj 里**。
# C21 只做了离线四环探针（原始 JSON 有键 · litellm 透得出 · 负对照 · provider 直给），
# 从没在一次真跑里见过读数 —— 要在花 ¥5 之前知道，否则两跑白跑（㉖ 同型教训：
# p2-rerun 的冒烟就是为了在花 ¥11 之前验三列非 None）。
#
# 用 --max-steps 3 压成几分钱：冒烟验的是仪器在不在，不是结果，不需要跑满 40 轮。
# 跑法：wsl -d swebench -e bash -lc 'bash /home/zixu/swe-bench-eval/scripts/areason_smoke.sh'
set -u

source ~/env.sh
cd ~/swe-bench-eval

echo "跑前余额: $(bash ~/s5_balance.sh)"
TZ=Asia/Shanghai date +"start 北京 %F %T %a"

PYTHONPATH=. .venv/bin/python -m agent.run \
  --run-id a-reason-smoke \
  --limit 1 \
  --workers 1 \
  --max-steps 3 \
  --model openai/deepseek-flash
rc=$?

TZ=Asia/Shanghai date +"end 北京 %F %T %a"
echo "退出码: $rc"
echo "跑后余额: $(bash ~/s5_balance.sh)"

echo "=== ㉖ 三列逐条读数 ==="
PYTHONPATH=. .venv/bin/python scripts/p2_rerun_check.py a-reason-smoke

echo "=== C21 仪器：reasoning_content 落没落盘 ==="
PYTHONPATH=. .venv/bin/python scripts/areason_read.py --stats a-reason-smoke
