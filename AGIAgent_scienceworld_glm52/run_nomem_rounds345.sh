#!/bin/bash
# ============================================================
# 无记忆臂 第3-5局 链式跑(镜像有记忆 iterative 的 won-skip 结构)
# 框架: 第1局=原始211筛选(复用论文数据), 第2局=v1(已完成, 解28)
#       第3局起: 每局只跑上一局仍未满分的任务, baseline模式(无记忆), 100步
# 链式: 本局完成后自动算剩余集, 启动下一局, 直到第5局
# ============================================================
set -uo pipefail
ROOT="/mnt/data/AGIAgent_scienceworld_glm52"
export TALES_CACHE_HOME=/mnt/data/tales_cache
export TALE_SUITE_ROOT=/home/agiagent/tale-suite

remaining() {  # $1 = 实验名, 输出未满分任务行号(逗号分隔)
python3 - "$ROOT/data/benchmark_results/$1" <<'PY'
import json, glob, re, sys
root = sys.argv[1]
rows = []
for p in glob.glob(f'{root}/outputs/*/logs/score_summary.json'):
    name = [x for x in p.split('/') if x.startswith('output_scienceworld_')][0]
    row = int(re.match(r'output_scienceworld_(\d+)_', name).group(1))
    if json.load(open(p)).get('score_rate') != 1.0:
        rows.append(row)
print(','.join(map(str, sorted(rows)))
      if rows else '')
PY
}

cd "$ROOT"
prev="sw_glm52_63_nomem"   # 第2局
for round in 3 4 5; do
  tasks=$(remaining "$prev")
  if [ -z "$tasks" ]; then
    echo "[$(date '+%F %T')] 第${round}局前已无剩余任务, 链结束"
    break
  fi
  n=$(echo "$tasks" | tr ',' '\n' | wc -l)
  exp="sw_63_nomem_round${round}"
  echo "[$(date '+%F %T')] 第${round}局: ${n} 个任务 -> $exp"
  python3 apps/scienceworld/run_all_tasks.py \
    --selection-mode fixed_total --fixed-dataset-split test \
    --task-list "$tasks" \
    --baseline --loops 100 --parallel-tasks 8 \
    --experiment-name "$exp" \
    > "nohup_${exp}.out" 2>&1
  echo "[$(date '+%F %T')] 第${round}局完成"
  prev="$exp"
done
echo "[$(date '+%F %T')] 全链完成"
