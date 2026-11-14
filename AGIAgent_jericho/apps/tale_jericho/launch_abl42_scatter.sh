#!/bin/bash
# ============================================================
# E1 — 散点化表示消融(abl42): 主目录, 6 并行, native, 旧key
# 命题: 支柱 A(有序叙事表示)是否必需
# 干预: curator 只写 (房间, 命令, Δ分) 原子三元组(对齐 RecMem 表示), 无顺序无叙事;
#       不写 knowledge 文件(检索只看 experiences 散点)
# 实现: AGIA_CURATOR_REPRESENTATION=scatter
# 对照: full n=2 (53.2±1.2); 判定: 掉回 ~34(底座)=叙事必需
# 启动时机: 等 abl39 结束(避免同 key 并发超载)
# ============================================================
set -euo pipefail
PROJECT_ROOT="~/AGIAgent_jericho"
ABL42="abl42_glm52_scatter_native_r1"
POLL=600

log() { echo "[$(date '+%F %T')] $*"; }
log "E1(abl42) 启动器: 等待 abl39 结束"

deadline=$(( $(date +%s) + 12*60*60 ))
while true; do
    pend=$(python3 - <<'PYEOF' 2>/dev/null || echo "ERR"
import json, glob
pend = 0
for p in glob.glob('~/AGIAgent_jericho/data/benchmark_results/abl39_glm52_no_knowledge_native_r2/outputs/*phase_records.json'):
    for r in json.load(open(p)):
        if r.get('play_status') in (None, 'pending'):
            pend += 1
print(pend)
PYEOF
)
    n_run=$(pgrep -fc "agia.py.*abl39" 2>/dev/null || true)
    if [ "$n_run" = "0" ] && [ "$pend" = "0" ]; then log "abl39 已结束"; break; fi
    [ "$(date +%s)" -ge "$deadline" ] && { log "超时 — 放弃"; exit 1; }
    log "abl39 运行中(进程 ${n_run}, pending ${pend}) — ${POLL}s 复查"
    sleep "$POLL"
done

# 自检
grep -q "AGIA_CURATOR_REPRESENTATION" "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" || { log "中止: 代码分支缺失"; exit 1; }
[ -f "$PROJECT_ROOT/apps/tale_jericho/prompts/phase_m_prompt_scatter.txt" ] || { log "中止: scatter 提示词缺失"; exit 1; }
for d in "$PROJECT_ROOT/data/benchmark_results/${ABL42}" "$PROJECT_ROOT/data/default/general/wiki/${ABL42}"; do
    [ -e "$d" ] && { log "中止: 已存在 $d"; exit 1; }
done
log "前置检查通过"

export TALES_CACHE_HOME=/mnt/data/tales_cache
export TALE_SUITE_ROOT=~/tale-suite
export AGIA_CURATOR_REPRESENTATION=scatter
cd "$PROJECT_ROOT"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name "$ABL42" \
  > "$PROJECT_ROOT/nohup_${ABL42}.out" 2>&1 < /dev/null &
log "已启动: PID $! (E1 scatter, p=6, native)"
