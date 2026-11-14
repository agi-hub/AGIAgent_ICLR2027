#!/bin/bash
# ============================================================
# abl35 — glm-5.2 FULL pipeline, native tool calling, run 2
# 参数与 abl34_glm52_full_r5 完全一致(native Tool_calling_format=True):
#   games: 13,24,51,53,8,44 | 10 iter x 110 loops | phase_m 30 | p=6
# 仅实验名不同: abl35_glm52_full_r6
#
# 用途: 等待 abl34 结束 + 固定延时后自动开跑(setsid 脱离本 shell)
# 启动方式: setsid nohup bash launch_abl35_delayed.sh &
# ============================================================

PROJECT_ROOT="~/AGIAgent_jericho"
DELAY_SECONDS=$((2 * 60 * 60))   # 2 小时
ABL34="abl34_glm52_full_r5"
ABL35="abl35_glm52_full_r6"
POLL=300                          # 每 5 分钟检查一次 abl34

log() { echo "[$(date '+%F %T')] $*"; }

log "abl35 延时启动器开始: 等 abl34 结束, 再延时 ${DELAY_SECONDS}s"

# ---- 阶段 1: 等 abl34 完全结束(最多 24h, 超时则放弃) ----
deadline=$(( $(date +%s) + 24*60*60 ))
while true; do
    n_run=$(pgrep -fc "agia.py.*${ABL34}" 2>/dev/null || true)
    pend=$(python3 - <<'PYEOF' 2>/dev/null || echo "ERR"
import json, glob
pend = 0
for p in glob.glob('~/AGIAgent_jericho/data/benchmark_results/abl34_glm52_full_r5/outputs/*phase_records.json'):
    for r in json.load(open(p)):
        if r.get('play_status') in (None, 'pending'):
            pend += 1
print(pend)
PYEOF
)
    if [ "$n_run" = "0" ] && [ "$pend" = "0" ]; then
        log "abl34 已完全结束(0 进程, 0 pending)"
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        log "超时(24h)abl34 仍未结束 — 放弃启动 abl35"
        exit 1
    fi
    log "abl34 仍在运行(进程 ${n_run}, pending ${pend}) — ${POLL}s 后复查"
    sleep "$POLL"
done

# ---- 阶段 2: 固定 2 小时延时 ----
log "开始 2 小时延时..."
sleep "$DELAY_SECONDS"
log "延时结束, 前置检查..."

# ---- 阶段 3: 前置检查 ----
# 3a. 配置必须是 native tool calling
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
if [ "$ok" != "OK" ]; then
    log "中止: Tool_calling_format 不是 True ($ok)"
    exit 1
fi
log "配置检查通过: Tool_calling_format=True (native)"

# 3b. 无其他 agia 实验在跑
others=$(pgrep -fc "agia.py" 2>/dev/null || true)
if [ "$others" != "0" ]; then
    log "中止: 仍有 ${others} 个 agia.py 进程在运行"
    exit 1
fi
log "无残留 agia 进程"

# 3c. 目标目录不冲突
for d in "$PROJECT_ROOT/data/benchmark_results/${ABL35}" \
         "$PROJECT_ROOT/data/default/general/wiki/${ABL35}"; do
    if [ -e "$d" ]; then
        log "中止: 已存在 $d"
        exit 1
    fi
done
log "目录检查通过: ${ABL35} 全新"

# ---- 阶段 4: 启动 ----
export TALES_CACHE_HOME=/mnt/data/tales_cache

log "启动 ${ABL35} (10 iter, p=6, native tool calling)"
cd "$PROJECT_ROOT"
setsid nohup python3 "$PROJECT_ROOT/apps/tale_jericho/run_all_tasks.py" \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name "$ABL35" \
  > "$PROJECT_ROOT/nohup_${ABL35}.out" 2>&1 < /dev/null &

log "已启动: PID $!  日志: nohup_${ABL35}.out"
