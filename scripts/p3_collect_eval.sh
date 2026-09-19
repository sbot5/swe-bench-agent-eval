#!/bin/bash
# 把 harness 写在 logs/evaluation/p3-r{1,2}/ 的评测报告，照 p2-rerun 的布局摊平进 results/evaluation/。2026-09-19。
# 布局：<instance>.report.json（每条出了 patch 的实例一份）+ results.json；run.json 与历史一样不入库。
set -eu
cd ~/swe-bench-eval

for RID in p3-r1 p3-r2; do
  mkdir -p "results/evaluation/$RID"
  cp "logs/evaluation/$RID/results.json" "results/evaluation/$RID/results.json"
  n=0
  for f in logs/evaluation/$RID/openai__deepseek-flash/*/report.json; do
    [ -e "$f" ] || continue
    id=$(basename "$(dirname "$f")")
    cp "$f" "results/evaluation/$RID/$id.report.json"
    n=$((n + 1))
  done
  echo "$RID: 复制 $n 份 report.json + results.json，目录共 $(ls "results/evaluation/$RID" | wc -l) 个文件"
  # ⚠️ resolved_ids 是名单，resolved_instances 是计数；total_instances 是 Verified 全集 500，不是这一跑的分母
  PYTHONPATH=. .venv/bin/python -c "
import json, sys
d = json.load(open(f'results/evaluation/{sys.argv[1]}/results.json'))
print('  submitted', d['submitted_instances'], '| resolved', sorted(i.split('__')[-1] for i in d['resolved_ids']),
      '| unresolved', sorted(i.split('__')[-1] for i in d['unresolved_ids']),
      '| empty', len(d['empty_patch_ids']), '| infra', d['infra_failure_instances'],
      '| ambiguous', d['ambiguous_failure_instances'], '| error', d['error_instances'])
" "$RID"
done
