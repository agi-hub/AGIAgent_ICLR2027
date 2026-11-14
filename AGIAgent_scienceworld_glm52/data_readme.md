# Data README: Wiki-Evolve Experiment Data Archive

This archive contains all raw experimental data supporting the results in the ablation study, comparison figures, and the academic manuscript.

---

## 1. Directory Structure

```
archive/
├── data_readme.md                    ← This file
├── benchmark_results/                ← Experiment outputs (trajectories, scores, logs)
│   ├── abl19_glm52_full/            ← GLM-5.2 full Wiki-Evolve
│   ├── abl19_glm52_no_wiki/         ← GLM-5.2 Naive ReAct (no memory)
│   ├── abl19_glm52_no_wiki_wm/      ← GLM-5.2 World Model only
│   ├── abl19_glm52_no_knowledge/    ← GLM-5.2 Experience+WM, no Knowledge
│   ├── abl16_pro_full/              ← DeepSeek-Pro full Wiki-Evolve
│   ├── abl18_gemini_full/           ← Gemini-2.5-Flash full Wiki-Evolve
│   └── abl18_gemini_test2/          ← Gemini Zork1 rerun (Tool_calling_format=False)
├── wiki/                             ← Persistent memory (knowledge + experience files)
│   ├── abl19_glm52_full/
│   ├── abl19_glm52_no_wiki/
│   ├── abl19_glm52_no_wiki_wm/
│   ├── abl19_glm52_no_knowledge/
│   ├── abl16_pro_full/
│   ├── abl18_gemini_full/
│   └── abl18_gemini_test2/
├── evotest_baseline/                 ← EvoTest (GLM-5.2) baseline results
│   └── run_6games_results.md
├── analysis/                         ← Analysis scripts and generated tables
│   ├── ablation.md                   ← Full ablation study results
│   ├── abl16_results.md             ← DeepSeek-Pro results report
│   ├── gemini_results.md            ← Gemini results report
│   ├── comparison_data.xlsx         ← All scores in Excel format
│   ├── plot_glm52_only.py           ← Plot script (GLM-5.2 only figure)
│   └── plot_evo_vs_ours.py          ← Plot script (GLM-5.2 + DeepSeek-Pro figure)
└── figures/                          ← Generated comparison figures
    ├── comparison_glm52_only.png
    ├── comparison_glm52_only.pdf
    ├── comparison_evo_vs_ours.png
    └── comparison_evo_vs_ours.pdf
```

---

## 2. Experiment-to-Data Mapping

### 2.1 Ablation Study (ablation.md)

| Condition | Experiment Name | Benchmark Data | Wiki Data | Description |
|---|---|---|---|---|
| **Full** | abl19_glm52_full | `benchmark_results/abl19_glm52_full/` | `wiki/abl19_glm52_full/` | Complete Wiki-Evolve: Knowledge + Experience + World Model + FATAL + Loop Detection |
| w/ (Exp, WM), w/o (Know, HP) | abl19_glm52_no_knowledge | `benchmark_results/abl19_glm52_no_knowledge/` | `wiki/abl19_glm52_no_knowledge/` | Experience + World Model only; no Knowledge retrieval or FATAL |
| w/ WM, w/o (Know, Exp, HP) | abl19_glm52_no_wiki_wm | `benchmark_results/abl19_glm52_no_wiki_wm/` | `wiki/abl19_glm52_no_wiki_wm/` | World Model only; no Knowledge/Experience retrieval or FATAL |
| Naive ReAct | abl19_glm52_no_wiki | `benchmark_results/abl19_glm52_no_wiki/` | `wiki/abl19_glm52_no_wiki/` | No memory assistance; only Loop Detection retained |

### 2.2 Cross-Model Comparison (Table 2 in paper, comparison figures)

| Model | Experiment Name | Benchmark Data | Wiki Data | Backbone |
|---|---|---|---|---|
| **GLM-5.2** | abl19_glm52_full | `benchmark_results/abl19_glm52_full/` | `wiki/abl19_glm52_full/` | glm-5.2 (BigModel coding API) |
| **DeepSeek-Pro** | abl16_pro_full | `benchmark_results/abl16_pro_full/` | `wiki/abl16_pro_full/` | deepseek-v4-pro |
| **Gemini-Flash** | abl18_gemini_full | `benchmark_results/abl18_gemini_full/` | `wiki/abl18_gemini_full/` | gemini-2.5-flash |
| Gemini (Zork1 rerun) | abl18_gemini_test2 | `benchmark_results/abl18_gemini_test2/` | `wiki/abl18_gemini_test2/` | gemini-2.5-flash (Tool_calling_format=False) |

> Note: Gemini Zork1 data in the comparison figures uses `abl18_gemini_test2` (rerun with chat-based tool calling); all other Gemini games use `abl18_gemini_full`.

### 2.3 Baseline Methods (comparison figures)

| Baseline | Source | Backbone | Data Location |
|---|---|---|---|
| EvoTest (GLM-5.2) | EvoTest benchmark run | glm-5.2 | `evotest_baseline/run_6games_results.md` |
| EvoTest (Gemini) | EvoTest benchmark | gemini-2.5-flash | Pre-existing data in `comparison_data.csv` |
| EvoPrompt (Gemini) | EvoTest benchmark | gemini-2.5-flash | Pre-existing data in `comparison_data.csv` |
| Reflexion (Gemini) | EvoTest benchmark | gemini-2.5-flash | Pre-existing data in `comparison_data.csv` |
| GRPO (Gemini) | EvoTest benchmark | gemini-2.5-flash | Pre-existing data in `comparison_data.csv` |
| Memory (Gemini) | EvoTest benchmark | gemini-2.5-flash | Pre-existing data in `comparison_data.csv` |
| Static (Gemini) | EvoTest benchmark | gemini-2.5-flash | Pre-existing data in `comparison_data.csv` |

---

## 3. File Formats within Each Experiment

### 3.1 `benchmark_results/{experiment}/outputs/`

Each experiment contains per-game, per-iteration output directories:

```
output_{app}_{task_idx}_{EnvName}_{phase}{iteration}_{timestamp}/
```

Where `phase` is `play` (gameplay episode) or `phasem` (curation phase).

Each directory contains `logs/` with:
- **`trajectory.jsonl`** — Structured per-round log: actions, observations, scores, FATAL blocks, loop warnings
- **`manager.log`** — Full agent reasoning and tool call trace
- **`manager.out`** — Terminal output (agent reasoning + tool results)
- **`score_summary.json`** — Final score summary for the episode
- **`agia.log`** — System initialization log (tool registration, config)

Plus a `phase_records.json` file at the experiment level summarizing all iterations:
```
benchmark_results/{experiment}/outputs/output_{app}_{task_idx}_{EnvName}_phase_records.json
```

### 3.2 `wiki/{experiment}/`

- **`knowledge/score_recipe_{game}.md`** — Semantic knowledge file (rewritten each iteration by curator)
- **`experiences/{date}/{game}.md`** — Append-only experience records (one entry per episode)
- **`.wiki_index.npz`** — Embedding index for semantic retrieval (BGE-M3, 1024-dim)

---

## 4. Configuration Summary

| Parameter | Value |
|---|---|
| Games | Detective (idx 13), Library (24), Zork1 (51), Zork3 (53), Balances (8), Temple (44) |
| Episodes per game | 10 |
| Steps per episode | 110 |
| Embedding model | BAAI/bge-m3 (SiliconFlow API) |
| wiki_memory_read limit | 3 queries per episode |
| Knowledge file size limit | 800 words (rewrite each iteration) |
| Loop detection threshold | Same (action, room) pair ≥5 times in 10-step window |
| FATAL exclusion | Actions appearing in scoring path are never tagged FATAL |
