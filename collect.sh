#!/usr/bin/env bash
# 把证据从 SWE-bench/logs/ 收进项目自己的 results/。
#
# 为什么要收出来：SWE-bench/ 是 clone 来的第三方仓库，被 .gitignore 排除，
# 而且随时可能被删掉重 clone。证据必须住在自己的项目里。
#
# 收什么（判据：小、且真的会有人看）
#   results.json  评测结论                      —— 核心证据
#   preds.json    Agent 产出的 patch            —— 核心证据
#   *.traj.json   完整决策链                    —— badcase 归因就靠它
# 不收
#   test_output.txt / run_instance.log  每实例几百 KB，只在排查单条时才看
#   build_images/                        几百 MB，没人看
set -euo pipefail
cd "$(dirname "$0")"
SRC=SWE-bench/logs
DST=results

for f in "$SRC"/evaluation/*/results.json; do
  [ -e "$f" ] || continue
  run=$(basename "$(dirname "$f")")
  mkdir -p "$DST/evaluation/$run" && cp "$f" "$DST/evaluation/$run/"
done

for f in "$SRC"/inference/*/preds.json; do
  [ -e "$f" ] || continue
  run=$(basename "$(dirname "$f")")
  mkdir -p "$DST/inference/$run" && cp "$f" "$DST/inference/$run/"
done

for f in "$SRC"/inference/*/*/*.traj.json; do
  [ -e "$f" ] || continue
  run=$(basename "$(dirname "$(dirname "$f")")")
  mkdir -p "$DST/inference/$run" && cp "$f" "$DST/inference/$run/"
done

echo "收进 $DST 的文件："
find "$DST" -type f | sort | sed 's/^/  /'
echo "合计 $(du -sh "$DST" | cut -f1)"
