#!/usr/bin/env python3
"""Token / curator-call cost accounting for our-harness conditions.

Sums per-call API usage lines ("Current conversation token usage - Input: X, Output: Y")
in manager.log of every play (actor) and phasem (curator) output directory.

Conditions (all GLM-5.2 harness, 6 games x 10 attempts):
  react    abl22_glm52_react          (matched no-memory control, actor only)
  gistonly abl46/48/49 (E7)           (episode archive, no schema page)
  bise     abl41/45/47 (E5)           (archive + schema page)
EvoTest-scaffold conditions do not log token usage and are excluded (stated in notes).
"""
import re, glob, os
from collections import defaultdict

DATA_ROOT = os.environ.get('AGIA_DATA_ROOT') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'data')
BR = os.path.join(DATA_ROOT, 'benchmark_results')
GAMES = {'Detective': 13, 'Library': 24, 'Zork1': 51, 'Zork3': 53, 'Balances': 8, 'Temple': 44}
RUNS = {
    'react':    ['abl22_glm52_react'],
    'gistonly': ['abl46_glm52_no_preextract_no_semantic_r1', 'abl48_glm52_no_preextract_no_semantic_r2', 'abl49_glm52_no_preextract_no_semantic_r3'],
    'bise':     ['abl41_glm52_no_preextract_native_r1', 'abl45_glm52_no_preextract_native_r2', 'abl47_glm52_no_preextract_native_r3'],
}
PAT = re.compile(r'token usage - Input: (\d+), Output: (\d+)')

def scan_dir(d):
    """(n_calls, in_tok, out_tok) for one play/phasem output dir; (0,0,0) if absent."""
    ml = os.path.join(d, 'logs', 'manager.log')
    if not os.path.exists(ml): return 0, 0, 0
    n = i = o = 0
    for line in open(ml, errors='ignore'):
        m = PAT.search(line)
        if m:
            n += 1; i += int(m.group(1)); o += int(m.group(2))
    return n, i, o

def audit_run(run):
    per = {'actor_calls': 0, 'actor_in': 0, 'actor_out': 0,
           'cur_calls': 0, 'cur_in': 0, 'cur_out': 0, 'attempts': 0,
           'actor_in_per_call_by_attempt': defaultdict(list)}
    for tid in GAMES.values():
        for att in range(1, 11):
            play = glob.glob(f'{BR}/{run}/outputs/output_tale_jericho_{tid:02d}_*_play{att}_*')
            pm   = glob.glob(f'{BR}/{run}/outputs/output_tale_jericho_{tid:02d}_*_phasem{att}_*')
            if play:
                per['attempts'] += 1
                n, i, o = scan_dir(play[0])
                per['actor_calls'] += n; per['actor_in'] += i; per['actor_out'] += o
                if n: per['actor_in_per_call_by_attempt'][att].append(i / n)
            if pm:
                n, i, o = scan_dir(pm[0])
                per['cur_calls'] += n; per['cur_in'] += i; per['cur_out'] += o
    return per

def main():
    NUM = ('actor_calls', 'actor_in', 'actor_out', 'cur_calls', 'cur_in', 'cur_out', 'attempts')
    for cond, runs in RUNS.items():
        agg = {k: 0 for k in NUM}
        agg['actor_in_per_call_by_attempt'] = defaultdict(list)  # type: ignore[assignment]
        for run in runs:
            r = audit_run(run)
            for k in NUM: agg[k] += r[k]
            for att, vals in r['actor_in_per_call_by_attempt'].items():
                agg['actor_in_per_call_by_attempt'][att].extend(vals)
        A = agg['attempts']
        if not A:
            print(f'== {cond}: NO DATA'); continue
        at = (agg['actor_in'] + agg['actor_out']) / A
        ct = (agg['cur_in'] + agg['cur_out']) / A
        tot = at + ct
        print(f'== {cond} ({len(runs)} runs, {A} attempts)')
        print(f'   actor : {agg["actor_calls"]/A:6.1f} calls/attempt, {at:9.0f} tok/attempt (in {agg["actor_in"]/A:.0f} / out {agg["actor_out"]/A:.0f})')
        print(f'   curator: {agg["cur_calls"]/A:6.1f} calls/attempt, {ct:9.0f} tok/attempt (in {agg["cur_in"]/A:.0f} / out {agg["cur_out"]/A:.0f})')
        print(f'   total : {tot:9.0f} tok/attempt | curator share {ct/tot*100 if tot else 0:4.1f}%')
        b = agg['actor_in_per_call_by_attempt']
        a1  = sum(b[1])/len(b[1]) if b[1] else 0
        a10 = sum(b[10])/len(b[10]) if b[10] else 0
        print(f'   actor input tokens/call: attempt1 {a1:.0f} -> attempt10 {a10:.0f} ({(a10/a1-1)*100 if a1 else 0:+.0f}% memory-context growth)')

if __name__ == '__main__':
    main()
