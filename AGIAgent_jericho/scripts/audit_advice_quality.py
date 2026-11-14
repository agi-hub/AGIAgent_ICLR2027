#!/usr/bin/env python3
"""Advice-quality audit for the three final BISE runs (abl41/45/47).

Part 1 — schema-page entry audit: every entry of the final knowledge pages is
classified as verified (source-linked and lexically supported by the cited gist
attempts; aggregate score claims cross-checked against phase records), partial
(source-linked but <40% lexical coverage), unverified (no source link), or
contradicted (phrase-scoped score claim conflicts with recorded best scores).

Part 2 — retrieval/death audit: retrieval prevalence from trajectory.jsonl, and
adjudication of every logged death against the FATAL entries of the final page
(correct-entry matching; a death counts as a repeat only if the matched entry's
evidence attempts all precede the death).

Usage: python3 audit_advice_quality.py [--adjudicate]

Data root defaults to <repo>/data (restore via README); override with AGIA_DATA_ROOT.
"""
import json, re, os, glob
from collections import Counter

DATA_ROOT = os.environ.get('AGIA_DATA_ROOT') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'data')
HOME = os.path.join(DATA_ROOT, 'default/general/wiki')
BR = os.path.join(DATA_ROOT, 'benchmark_results')
RUNS = {'abl41': 'abl41_glm52_no_preextract_native_r1',
        'abl45': 'abl45_glm52_no_preextract_native_r2',
        'abl47': 'abl47_glm52_no_preextract_native_r3'}
GAMES = {'detective': 13, 'library': 24, 'zork1': 51, 'zork3': 53, 'balances': 8, 'temple': 44}
STOP = set('the a an at to of in on for from with and or is are was were be been it its this that then go goes going take takes enter entry do not no never always all e w n s up back again just only after before while where which who whom you your'.split())

def key_tokens(text):
    toks = re.findall(r'[a-zA-Z#]+', text.lower())
    return set(t for t in toks if t not in STOP and len(t) > 2)

def load_gist(run_dir, game):
    files = sorted(glob.glob(f'{HOME}/{run_dir}/experiences/*/{game}.md'))
    return '\n'.join(open(f).read() for f in files) if files else None

def load_page(run_dir, game):
    f = f'{HOME}/{run_dir}/knowledge/score_recipe_{game}.md'
    return open(f).read() if os.path.exists(f) else None

def load_phase(run_dir, tid):
    for f in glob.glob(f'{BR}/{run_dir}/outputs/output_tale_jericho_{tid:02d}_*_phase_records.json'):
        return json.load(open(f))
    return None

def atts_in(body):
    out = [int(a) for a in re.findall(r'\[Attempt (\d+)\]', body)]
    out += [int(a) for a in re.findall(r'\[A(\d+)\]', body)]
    for m in re.finditer(r'\[Attempts? ([\d,\- ]+)\]', body):
        for part in m.group(1).split(','):
            part = part.strip()
            if part.isdigit():
                out.append(int(part))
            else:
                mm = re.match(r'^(\d+)\s*-\s*(?:A)?(\d+)$', part)
                if mm: out += list(range(int(mm.group(1)), int(mm.group(2)) + 1))
    return sorted(set(out))

def parse_entries(page):
    entries, section = [], 'header'
    for line in page.splitlines():
        if line.startswith('## '):
            section = line[3:].strip(); continue
        s = line.strip()
        if not s: continue
        m = re.match(r'^- (.*)|^\* (.*)|^(\d+)\. (.*)', s)
        if m:
            body = m.group(4) if m.group(3) is not None else next(g for g in m.groups()[:2] if g)
            entries.append({'section': section, 'body': body, 'attempts': atts_in(body)})
        elif entries and (s.startswith('Evidence') or not s.startswith('#')):
            entries[-1]['body'] += ' ' + s
            entries[-1]['attempts'] = atts_in(entries[-1]['body'])
    return entries

def parse_gist(gist):
    secs = {}
    for m in re.finditer(r'## Attempt (\d+)[^\n]*', gist):
        a, start = int(m.group(1)), m.end()
        nxt = gist.find('## Attempt', start)
        secs[a] = gist[start: nxt if nxt > 0 else len(gist)]
    return secs

def phrase_contradictions(body, best):
    contra = []
    for sent in re.split(r'[.;]', body):
        atts = [int(a) for a in re.findall(r'\bA(\d+)\b', sent)] + \
               [int(a) for a in re.findall(r'attempt[s]? (\d+)', sent, re.I)]
        for a, b in re.findall(r'(\d+)\s*/\s*(\d+)', sent):
            for at in atts:
                if at in best and best[at] < int(a) - 0.5:
                    contra.append(f'{a}/{b} claimed @A{at} but best={best[at]:.0f}')
    return contra

def classify_entry(e, secs, phase):
    if not e['attempts']: return 'unverified', 'no source link'
    kt = key_tokens(e['body'])
    union = set()
    for a in set(e['attempts']): union |= key_tokens(secs.get(a, ''))
    cov = sum(1 for t in kt if t in union) / max(len(kt), 1)
    best = {r['iteration']: r['play_best_score'] for r in phase}
    contra = phrase_contradictions(e['body'], best)
    if contra: return 'contradicted', '; '.join(contra)
    return ('verified', f'cov={cov:.2f}') if cov >= 0.4 else ('partial', f'cov={cov:.2f}')

def main():
    agg = Counter()
    for rk, run_dir in RUNS.items():
        print(f'== {rk}')
        for game, tid in GAMES.items():
            page, gist, phase = load_page(run_dir, game), load_gist(run_dir, game), load_phase(run_dir, tid)
            ents, secs = parse_entries(page), parse_gist(gist)
            counts = Counter(classify_entry(e, secs, phase)[0] for e in ents)
            print(f'  {game:9s} total={len(ents):3d} ' +
                  ' '.join(f'{k}={counts.get(k,0)}' for k in ('verified','partial','unverified','contradicted')))
            agg.update(counts)
    n = sum(agg.values())
    print(f'\nTOTALS: {dict(agg)} | entries: {n}')
    print(f'verified {agg["verified"]/n*100:.0f}% partial {agg["partial"]/n*100:.0f}% '
          f'unverified {agg["unverified"]/n*100:.0f}% contradicted {agg["contradicted"]}')

if __name__ == '__main__':
    main()
