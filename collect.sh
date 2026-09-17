#!/usr/bin/env bash
# 把证据从 harness 的 logs/ 收进项目自己的 results/。
#
# 为什么要收出来：SWE-bench/ 是 clone 来的第三方仓库，被 .gitignore 排除，
# 而且随时可能被删掉重 clone。证据必须住在自己的项目里。
#
# 收什么（判据：小、且真的会有人看）
#   results.json  评测结论                      —— 核心证据
#   report.json   每实例逐条 FAIL_TO_PASS 明细  —— badcase 归因就靠它，每份几百字节
#   preds.json    Agent 产出的 patch            —— 核心证据
#   *.traj.json   完整决策链                    —— badcase 归因就靠它
# 不收
#   test_output.txt / run_instance.log  每实例几百 KB，只在排查单条时才看
#   build_images/                        几百 MB，没人看
#
# 已纠正的错误（2026-09-17）：原来写死 SRC=SWE-bench/logs，但 harness 已改成落在
# 仓库根 logs/，S4 的证据因此是手工收的。改成两个位置都扫（旧跑次还在 SWE-bench/logs/）。
# 同时：agent/run.py 现在把 preds.json 与 *.traj.json 直接写进 results/inference/<run-id>/，
# 下面两个 inference 循环只对 S3 之前的旧跑次有用，保留但已是 no-op。
set -euo pipefail
cd "$(dirname "$0")"
SRCS="logs SWE-bench/logs"
DST=results

# 用法：./collect.sh [run-id ...]
#   不带参数 = 收所有跑次（原行为）；带参数 = 只收指定跑次。
#   加过滤是因为新增的 report.json 收集会把所有历史跑次一并扫出来，
#   而那些跑次的归因早就写完了，不该在这时候涌进 git。
want() {
  [ "$#" -eq 0 ] && return 0
  for r in "$@"; do [ "$r" = "$RUN" ] && return 0; done
  return 1
}

for SRC in $SRCS; do
  for f in "$SRC"/evaluation/*/results.json; do
    [ -e "$f" ] || continue
    RUN=$(basename "$(dirname "$f")"); run=$RUN
    want "$@" || continue
    mkdir -p "$DST/evaluation/$run" && cp "$f" "$DST/evaluation/$run/"
  done

  # report.json 埋在 logs/evaluation/<run>/<model>/<instance>/report.json，深度不定，用 find
  for d in "$SRC"/evaluation/*/; do
    [ -d "$d" ] || continue
    RUN=$(basename "$d"); run=$RUN
    want "$@" || continue
    find "$d" -name report.json | while read -r f; do
      inst=$(basename "$(dirname "$f")")
      mkdir -p "$DST/evaluation/$run" && cp "$f" "$DST/evaluation/$run/$inst.report.json"
    done
  done

  for f in "$SRC"/inference/*/preds.json; do
    [ -e "$f" ] || continue
    RUN=$(basename "$(dirname "$f")"); run=$RUN
    want "$@" || continue
    mkdir -p "$DST/inference/$run" && cp "$f" "$DST/inference/$run/"
  done

  for f in "$SRC"/inference/*/*/*.traj.json; do
    [ -e "$f" ] || continue
    RUN=$(basename "$(dirname "$(dirname "$f")")"); run=$RUN
    want "$@" || continue
    mkdir -p "$DST/inference/$run" && cp "$f" "$DST/inference/$run/"
  done
done

echo "收进 $DST 的文件（$# 个跑次过滤：${*:-全部}）："
if [ "$#" -eq 0 ]; then
  find "$DST" -type f | sort | sed 's/^/  /'
else
  for r in "$@"; do find "$DST" -path "*/$r/*" -type f | sort | sed 's/^/  /'; done
fi
echo "合计 $(du -sh "$DST" | cut -f1)"
