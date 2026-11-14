#!/bin/bash
# ============================================================
# 无记忆臂 r3: 完整5局链(等 r2 链跑完后自动启动, 避免并发超限)
# r3 用独立任务行号清单起点同 r2; 并行3
# ============================================================
set -uo pipefail
ROOT="/mnt/data/AGIAgent_scienceworld_glm52"
export TALES_CACHE_HOME=/mnt/data/tales_cache
export TALE_SUITE_ROOT=/home/agiagent/tale-suite
TASKS="1,2,3,4,5,6,7,8,9,12,19,20,21,23,24,25,26,27,31,35,58,59,60,61,63,64,65,66,78,82,84,85,86,89,92,127,128,129,130,131,132,133,134,135,136,137,138,140,141,142,144,153,163,184,188,189,194,199,205,206,207,209,210"

remaining() {
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

# --- 等 r2 链结束(run_nomem2_full_chain 进程消失) ---
echo "[$(date '+%F %T')] 等待 r2 链完成..."
while pgrep -f "run_nomem2_full_chain.sh" > /dev/null; do
  sleep 300
done
echo "[$(date '+%F %T')] r2 链已完成, 启动 r3"

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
  exp="sw_63_nomem3_round${round}"
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
echo "[$(date '+%F %T')] 无记忆臂 r3 全链完成"
