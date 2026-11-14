#!/bin/bash
# ============================================================
# 无记忆臂 第2次采样(r2): 完整5局链
# 第1局: 63 任务全量 baseline; 第2-5局: 每局只跑上局未满分任务
# (与 r1 臂同构: r1 臂 = v1(63) + round3/4/5)
# ============================================================
set -uo pipefail
ROOT="/mnt/data/AGIAgent_scienceworld_glm52"
export TALES_CACHE_HOME=/mnt/data/tales_cache
export TALE_SUITE_ROOT=~/tale-suite
TASKS="1,2,3,4,5,6,7,8,9,12,19,20,21,23,24,25,26,27,31,35,58,59,60,61,63,64,65,66,78,82,84,85,86,89,92,127,128,129,130,131,132,133,134,135,136,137,138,140,141,142,144,153,163,184,188,189,194,199,205,206,207,209,210"

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
print(','.join(map(str, sorted(rows))) if rows else '')
PY
}

cd "$ROOT"
prev=""
for round in 1 2 3 4 5; do
  if [ "$round" -eq 1 ]; then
    tasks="$TASKS"
  else
    tasks=$(remaining "$prev")
    if [ -z "$tasks" ]; then
      echo "[$(date '+%F %T')] 第${round}局前已无剩余任务, 链结束"
      break
    fi
  fi
  n=$(echo "$tasks" | tr ',' '\n' | wc -l)
  exp="sw_63_nomem2_round${round}"
  echo "[$(date '+%F %T')] 第${round}局: ${n} 个任务 -> $exp"
  python3 apps/scienceworld/run_all_tasks.py \
    --selection-mode fixed_total --fixed-dataset-split test \
    --task-list "$tasks" \
    --baseline --loops 100 --parallel-tasks 3 \
    --experiment-name "$exp" \
    > "nohup_${exp}.out" 2>&1
  echo "[$(date '+%F %T')] 第${round}局完成"
  prev="$exp"
done
echo "[$(date '+%F %T')] 无记忆臂 r2 全链完成"
