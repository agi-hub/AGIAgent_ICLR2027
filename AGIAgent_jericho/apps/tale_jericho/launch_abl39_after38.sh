#!/bin/bash
# ============================================================
# abl39 — −语义(no_knowledge) native r2
# 参数与 abl38 完全一致: Tool_calling_format=True, AGIA_WIKI_ABLATION=no_knowledge,
#   games 13,24,51,53,8,44 | 10 iter x 110 | phase_m 30 | p=6
# 用途: −语义臂 native n=2(与 abl38 同协议成对)
# 启动: 等 abl38 结束 + 前置自检后立即开跑(无额外延时, 接力式)
# ============================================================

PROJECT_ROOT="~/AGIAgent_jericho"
ABL38="abl38_glm52_no_knowledge_native_r1"
ABL39="abl39_glm52_no_knowledge_native_r2"
POLL=300

log() { echo "[$(date '+%F %T')] $*"; }

log "abl39 启动器开始: 等待 abl38 结束"

deadline=$(( $(date +%s) + 24*60*60 ))
while true; do
    n_run=$(pgrep -fc "agia.py.*${ABL38}" 2>/dev/null || true)
    pend=$(python3 - <<'PYEOF' 2>/dev/null || echo "ERR"
import json, glob
pend = 0
for p in glob.glob('~/AGIAgent_jericho/data/benchmark_results/abl38_glm52_no_knowledge_native_r1/outputs/*phase_records.json'):
    for r in json.load(open(p)):
        if r.get('play_status') in (None, 'pending'):
            pend += 1
print(pend)
PYEOF
)
    if [ "$n_run" = "0" ] && [ "$pend" = "0" ]; then
        log "abl38 已完全结束"
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        log "超时(24h)abl38 仍未结束 — 放弃"
        exit 1
    fi
    log "abl38 运行中(进程 ${n_run}, pending ${pend}) — ${POLL}s 后复查"
    sleep "$POLL"
done

# ---- 前置自检 ----
ok=$(python3 - <<'PYEOF'
import re
vals = []
for p in ('~/AGIAgent_jericho/config/config.txt',
          '~/AGIAgent_jericho/apps/tale_jericho/config.txt'):
    txt = open(p, encoding='utf-8').read()
    m = re.search(r'^\s*Tool_calling_format\s*=\s*(\S+)', txt, re.M)
    vals.append(m.group(1) if m else 'MISSING')
print('OK' if all(v.lower() in ('true', '1', 'yes', 'on') for v in vals) else 'BAD:' + ','.join(vals))
PYEOF
)
[ "$ok" = "OK" ] || { log "中止: Tool_calling_format 非 True ($ok)"; exit 1; }
log "配置检查通过 (native)"

others=$(pgrep -fc "agia.py" 2>/dev/null || true)
[ "$others" = "0" ] || { log "中止: 仍有 ${others} 个 agia.py"; exit 1; }

for d in "$PROJECT_ROOT/data/benchmark_results/${ABL39}" \
         "$PROJECT_ROOT/data/default/general/wiki/${ABL39}"; do
    [ -e "$d" ] && { log "中止: 已存在 $d"; exit 1; }
done
log "前置检查全部通过"

# ---- 启动 ----
export AGIA_WIKI_ABLATION=no_knowledge
export TALES_CACHE_HOME=/mnt/data/tales_cache
cd "$PROJECT_ROOT"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name "$ABL39" \
  --ablation no_knowledge \
  > "$PROJECT_ROOT/nohup_${ABL39}.out" 2>&1 < /dev/null &
log "已启动: PID $!  日志: nohup_${ABL39}.out"
