#!/bin/bash
# 把 harness 写在 logs/evaluation/p4-r{1,2}/ 的评测报告，照 p3 的布局摊平进 results/evaluation/。2026-09-22。
# 布局：<instance>.report.json（每条出了 patch 的实例一份）+ results.json；run.json 与历史一样不入库。
#
# ⚠️ 比 p3_collect_eval.sh 多收一样东西：EVAL-P4-staged.md §8.4 的结论建立在**测试日志原文**上
#   （两条 harness 标 ambiguous 的实例，日志里一条是 `1 failed, 19 passed`、一条是 ImportError），
#   而 logs/ 在 .gitignore 里。不收进来，那条结论出了这台机器就核不了。
set -eu
cd ~/swe-bench-eval

# §8.4 逐条读过日志的两条
declare -A KEEP_LOG=(
  ["p4-r1"]="pylint-dev__pylint-8898"
  ["p4-r2"]="pylint-dev__pylint-4551"
)

for RID in p4-r1 p4-r2; do
  mkdir -p "results/evaluation/$RID"
  cp "logs/evaluation/$RID/results.json" "results/evaluation/$RID/results.json"
  n=0
  for f in logs/evaluation/$RID/openai__deepseek-flash/*/report.json; do
    [ -e "$f" ] || continue
    id=$(basename "$(dirname "$f")")
    cp "$f" "results/evaluation/$RID/$id.report.json"
    n=$((n + 1))
  done
  iid="${KEEP_LOG[$RID]}"
  src="logs/evaluation/$RID/openai__deepseek-flash/$iid/test_output.txt"
  if [ -e "$src" ]; then
    cp "$src" "results/evaluation/$RID/$iid.test_output.txt"
    echo "$RID: 另收 §8.4 的日志原文 $iid.test_output.txt"
  else
    echo "$RID: ⚠️ 没找到 $src —— §8.4 的证据未入库，照实记" >&2
  fi
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
