#!/bin/bash
# 把 harness 写在 logs/evaluation/p2-rerun/ 的评测报告，照 p2-mine 的布局摊平进 results/evaluation/p2-rerun/。2026-09-19。
# 布局：<instance>.report.json（每条出了 patch 的实例一份）+ results.json；run.json 与 p2-mine 一样不入库。
set -eu
cd ~/swe-bench-eval

echo "p2-mine 两处 results.json 是否逐字节相同（确认 P2 当时就是原样复制）:"
cmp logs/evaluation/p2-mine/results.json results/evaluation/p2-mine/results.json && echo "  相同"
n_same=0
for f in logs/evaluation/p2-mine/openai__deepseek-flash/*/report.json; do
  id=$(basename "$(dirname "$f")")
  cmp -s "$f" "results/evaluation/p2-mine/$id.report.json" && n_same=$((n_same + 1))
done
echo "  p2-mine 逐条 report.json 与 logs 相同: $n_same 条"

mkdir -p results/evaluation/p2-rerun
cp logs/evaluation/p2-rerun/results.json results/evaluation/p2-rerun/results.json
n=0
for f in logs/evaluation/p2-rerun/openai__deepseek-flash/*/report.json; do
  id=$(basename "$(dirname "$f")")
  cp "$f" "results/evaluation/p2-rerun/$id.report.json"
  n=$((n + 1))
done
echo "p2-rerun: 复制 $n 份 report.json + results.json"
ls results/evaluation/p2-rerun | wc -l
