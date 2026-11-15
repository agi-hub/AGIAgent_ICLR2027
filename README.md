# AGIAgent_ICLR2027 — Code & Data Package (Code / Data / Archives)

> Date: 2026-11-14 | Paper: brain-inspired-agent (ICLR 2027 submission)
> Contains all ablation experiment code & data (n=3 finalized) for Jericho + ScienceWorld.

## Archives (ready for distribution) — 624 MB total

Download from the [release page](https://github.com/agi-hub/AGIAgent_ICLR2027/releases/tag/v1.0-data):

| Archive | Size | Contents | score_summary |
|---|---|---|---|
| `jericho_results_core.tar.gz` | 244M | **26 core experiments**: E5 main n=3 (abl41/45/47), E7 n=3 (46/48/49), ladder arms n=3 (scatter 42/54/57, no-time 43/55/58, pure-episodic 44/53/56), full n=2 (34/35), −semantic n=2 (38/39), −guard n=2 (36/37), no-memory base (19_no_wiki), AutoManual (50/51/52), N=50 long-run (59) | 3508 |
| `jericho_results_deprecated.tar.gz` | 244M | 41 deprecated chat-era / early runs (abl7-33 etc.; basis of paper Table 2 deprecation) | 5092 |
| `scienceworld_results.tar.gz` | 108M | All 20 SW experiments: 211-pair source run (test_full), iterative r1-3 (memory arm), no-memory chains ×3 (nomem/nomem2/nomem3), v2 partial run | 1833 |
| `wiki_memory_jericho.tar.gz` | 3.7M | Wiki memory for 87 Jericho experiments (semantic pages `score_recipe_*.md` + gist `experiences/`) | — |
| `wiki_memory_scienceworld.tar.gz` | 0.3M | Wiki memory for 7 SW experiments | — |
| `extras.tar.gz` | 24M | long_term_memory (early memory data) + reference_papers (PDFs) | — |

score_summary total: 10433, consistent with the data package. The Jericho archives extract directly to experiment directories (subdirs of `benchmark_results`); the SW archive extracts to a `benchmark_results/` directory.

## Directory Layout

```
<repo root>/
├── AGIAgent_jericho/                   # Jericho main project (code + analysis docs)
│   ├── src/ apps/ prompts/ config/     # code & prompts
│   ├── experiment_notes/               # analysis outputs (summaries/details/figures)
│   └── README_jericho_sciworld.md      # ★ ops manual (incl. SW §5.1)
└── AGIAgent_scienceworld_glm52/        # ScienceWorld project (code + chain scripts)

<data root>/                            # after extracting the release archives
├── AGIAgent_jericho_data/
│   ├── benchmark_results/              # 67 experiments × (phase_records + trajectory + score_summary)
│   ├── default/general/wiki/           # wiki memory, 87 experiments
│   ├── long_term_memory/               # early-era memory data (embedding/texts caches)
│   └── reference_papers/               # reference PDFs (originally papers/)
└── AGIAgent_scienceworld_glm52_data/
    ├── benchmark_results/              # 20 SW experiments (211 source / iterative r1-3 / nomem chains)
    └── default/general/wiki/           # SW wiki memory
```

## Restoring Data into the Code Folder

**Option 1 (move/copy for a standalone runnable project)**:

```bash
# Jericho: put data back as data/
mv  <data root>/AGIAgent_jericho_data  <repo root>/AGIAgent_jericho/data
# ScienceWorld: same
mv  <data root>/AGIAgent_scienceworld_glm52_data  <repo root>/AGIAgent_scienceworld_glm52/data
```

Two items originally lived at the **project root** (not inside `data/`):
```bash
mv <data root>/AGIAgent_jericho_data/long_term_memory   <repo root>/AGIAgent_jericho/
mv <data root>/AGIAgent_jericho_data/reference_papers   <repo root>/AGIAgent_jericho/papers
```
(Not required for reproducing experiments. To keep the data package intact, replace `mv` with `cp -a`.)

**Option 2 (symlink, no extra space; matches the original setup)**:

```bash
ln -s <data root>/AGIAgent_jericho_data            <repo root>/AGIAgent_jericho/data
ln -s <data root>/AGIAgent_scienceworld_glm52_data <repo root>/AGIAgent_scienceworld_glm52/data
```

After restoring, launch experiments via the template in `AGIAgent_jericho/README_jericho_sciworld.md` §3.1
(dependencies: `TALES_CACHE_HOME` game cache, `TALE_SUITE_ROOT` tale-suite, API key in `apps/*/config.txt`).

## Integrity Check Values (self-check after restore)

| Item | Expected |
|---|---|
| Jericho benchmark_results experiment dirs | 67 (incl. abl53/56 merged from the 20260917 copy) |
| Jericho score_summary.json total | 8600 |
| SW benchmark_results experiment dirs | 20 |
| SW score_summary.json total | 1833 |
| phase_records.json | 416 (Jericho) + 416 (SW) |

## Key Documents (inside the code package)

- `AGIAgent_jericho/README_jericho_sciworld.md` — ★ Ops manual: protocols / ablation switches / analysis commands / pitfalls / SW §5.1
- `AGIAgent_jericho/experiment_notes/ablations_final_summary.md` — Final summary (read first)
- `AGIAgent_jericho/experiment_notes/ablations_detailed_scores.md` — Per-episode details; last two sections = the finalized A2/A3 audits
- `AGIAgent_jericho/experiment_notes/ablations_summary_table.csv` — One row per experiment, 51 rows

### Audit scripts

`AGIAgent_jericho/scripts/` contains the two audit scripts backing appendix tables A2/A3 (usage, data dependencies and expected outputs: see ops manual §6.1):

- `audit_advice_quality.py` — advice-quality audit: classifies all 463 schema-page entries (80% verified / 14% partial / 6% unverified / 0 contradicted) and adjudicates the 38 logged deaths (0 violated a complete warning).
