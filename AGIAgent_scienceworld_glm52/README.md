# Wiki-Evolve: Gradient-Free Test-Time Learning for Jericho Text Adventure Games

This repository contains the Wiki-Evolve framework — a persistent memory system that enables LLM agents to progressively improve their performance across repeated playthroughs of Jericho text adventure games, without gradient updates.

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running Experiments](#running-experiments)
- [Experiment Parameters](#experiment-parameters)
- [Output Structure](#output-structure)
- [Ablation Modes](#ablation-modes)
- [Analysis](#analysis)
- [Key Source Files](#key-source-files)

---

## Overview

Wiki-Evolve organizes agent experience into a three-tier persistent memory:

1. **Semantic Knowledge** ($\mathcal{S}$) — Distilled scoring recipes and death traps, rewritten each iteration by a curator agent.
2. **Episodic Experience** ($\mathcal{E}$) — Append-only verbatim records of each playthrough, with evidence links to knowledge entries.
3. **World Model Graph** ($\mathcal{G}$) — In-memory spatial representation tracking room connectivity, tried/untried actions, and frontier candidates.

The system operates in an iterative pipeline: **Episode 1 → Curation → Episode 2 → Curation → ... → Episode K**.

Two safety mechanisms run during gameplay:
- **Hard Protection (FATAL)**: Intercepts actions tagged as unconditionally fatal before they reach the game engine.
- **Loop Detection**: Detects behavioral stagnation via (action, room) pair analysis with actionable untried-command suggestions.

---

## Requirements

- Python 3.10+
- [Tale-Suite](https://github.com/agi-hub/tale-suite) (Jericho game environment wrapper)
- An LLM API (OpenAI-compatible or Anthropic-compatible)
- An embedding model API (for semantic retrieval; uses BAAI/bge-m3 by default)

### Key Python Dependencies

```bash
pip install -r requirements.txt
```

The Tale-Suite must be installed separately. It provides the `tales` package and Jericho game data.

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd AGIAgent_jericho

# Install Python dependencies
pip install -r requirements.txt

# Install Tale-Suite (provides Jericho environments)
cd /path/to/tale-suite
pip install -e .
```

---

## Configuration

Each LLM backbone uses a separate app directory under `apps/`. Each app contains:

```
apps/tale_jericho/
├── config.txt              ← LLM API configuration
├── run_all_tasks.py        ← Experiment runner script
└── prompts/
    ├── system_prompt.txt    ← Agent system prompt (SURVIVAL FIRST, strategy)
    ├── phase_m_prompt.txt   ← Curator prompt (knowledge rewrite rules)
    ├── rules_prompt.txt     ← Additional rules (if any)
    └── tool_prompt.json     ← Tool descriptions (tale_jericho_action, query_wm, wiki_memory_read)
```

### `config.txt` Example (GLM-5.2)

```ini
LANG=en

api_key=YOUR_API_KEY
api_base=https://open.bigmodel.cn/api/coding/paas/v4/
model=glm-5.2
max_tokens=32768

streaming=True
Tool_calling_format=False
tool_call_parse_format=xml

# Embedding for semantic retrieval
embedding_model=BAAI/bge-m3
embedding_model_api_key=YOUR_EMBEDDING_KEY
embedding_model_api_base=https://api.siliconflow.cn/v1

# History compression
summary_trigger_length=100000
compression_target_length=50000
compression_strategy=llm_summary
keep_recent_rounds=0
```

### Creating a New Model Configuration

To use a different LLM backbone:

1. Copy an existing app directory: `cp -r apps/tale_jericho apps/tale_jericho_newmodel`
2. Edit `apps/tale_jericho_newmodel/config.txt` with the new model's API credentials.
3. In `apps/tale_jericho_newmodel/run_all_tasks.py`, set:
   ```python
   APP_NAME = "tale_jericho_newmodel"
   TOOL_PREFIX = "tale_jericho"  # keep this — it maps to the tool name
   ```
4. Register the new app in `src/tool_executor.py`:
   - Add to `_detect_tale_app_name()` set.
   - Add to `tale_app_tool_specs` dict with `["tale_jericho_action", "query_wm"]`.

---

## Running Experiments

### Single Experiment

```bash
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 \
  --phase-m-loops 30 \
  --max-iterations 10 \
  --parallel-tasks 2 \
  --experiment-name my_experiment
```

### With Ablation

```bash
# No-wiki baseline (Naive ReAct)
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 2 \
  --experiment-name my_no_wiki \
  --ablation no_wiki
```

### Background Execution

```bash
setsid nohup python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name my_experiment \
  > nohup_my_experiment.out 2>&1 < /dev/null &
```

---

## Experiment Parameters

| Parameter | Flag | Description |
|---|---|---|
| `--task-list` | `"[13,24,...]"` | 1-based game indices from the Jericho task list |
| `--play-loops` | `110` | Maximum LLM interaction rounds per episode (game steps) |
| `--phase-m-loops` | `30` | Maximum rounds for the curation phase |
| `--max-iterations` | `10` | Number of play+curation iterations ($K$) |
| `--parallel-tasks` | `6` | Number of games to run concurrently |
| `--experiment-name` | `"abl19_glm52_full"` | Namespace for data directories |
| `--ablation` | `"no_wiki"` | Ablation mode (see below) |
| `--baseline` | (flag) | Run as single-pass baseline (no curation) |

### Available Jericho Games

| Index | Game | Max Score |
|---|---|---|
| 2 | Acorncourt | 30 |
| 3 | Advent | 350 |
| 4 | Adventureland | 100 |
| 5 | Afflicted | 75 |
| 8 | Balances | 51 |
| 11 | Cutthroat | 250 |
| 12 | Deephome | 300 |
| 13 | Detective | 360 |
| 15 | Enchanter | 400 |
| 24 | Library | 30 |
| 30 | Murdac | 250 |
| 34 | Pentari | 400 |
| 40 | Snacktime | 50 |
| 41 | Sorcerer | 400 |
| 42 | Spellbrkr | 600 |
| 44 | Temple | 35 |
| 51 | Zork1 | 350 |
| 52 | Zork2 | 400 |
| 53 | Zork3 | 7 |

Use `--task-count` without `--task-list` to see the full list.

---

## Output Structure

```
data/
├── benchmark_results/{experiment_name}/
│   ├── run_manifest.json              ← Experiment metadata
│   └── outputs/
│       ├── output_{app}_{idx}_{env}_phase_records.json   ← Per-game iteration scores
│       ├── output_{app}_{idx}_{env}_play{N}_{ts}/        ← Episode N output
│       │   └── logs/
│       │       ├── trajectory.jsonl    ← Per-round actions, scores, observations
│       │       ├── manager.log         ← Full agent reasoning trace
│       │       ├── manager.out         ← Terminal output
│       │       ├── score_summary.json  ← Episode final scores
│       │       └── agia.log            ← System init log
│       └── output_{app}_{idx}_{env}_phasem{N}_{ts}/      ← Curation phase N output
│           └── logs/
│               └── ...
└── default/general/
    ├── wiki/{experiment_name}/
    │   ├── knowledge/
    │   │   └── score_recipe_{game}.md  ← Semantic knowledge (rewritten each iteration)
    │   ├── experiences/
    │   │   └── {date}/{game}.md        ← Append-only episode records
    │   └── .wiki_index.npz            ← Embedding index (auto-generated)
    └── experience/{experiment_name}/
        └── logs/                       ← Curation phase logs
```

---

## Ablation Modes

The `--ablation` flag controls which memory components are active:

| Mode | Knowledge | Experience | World Model | FATAL | Loop Detection |
|---|---|---|---|---|---|
| *(none)* — Full | ✓ | ✓ | ✓ | ✓ | ✓ |
| `no_wiki` | ✗ | ✗ | ✗ | ✗ | ✓ |
| `no_knowledge` | ✗ | ✓ | ✓ | ✗ | ✓ |
| `no_experiences` | ✓ | ✗ | ✓ | ✓ | ✓ |
| `no_world_model` | ✓ | ✓ | ✗ | ✓ | ✓ |

> Note: The World Model (query_wm + graph) can be independently enabled for `no_wiki` by modifying the ablation guards in `src/tools/tale_jericho_tools.py`. See the ablation study in `ablation.md` for the specific configuration used.

---

## Analysis

### Checking Progress

```python
import json, glob

prefix = "my_experiment"
for game in ['Detective', 'Library', 'Zork1', 'Zork3', 'Balances', 'Temple']:
    files = glob.glob(f'data/benchmark_results/{prefix}/outputs/*{game}*phase_records.json')
    data = json.load(open(files[0]))
    scores = [float(it.get('play_current_score', 0) or 0) for it in data if isinstance(it, dict)]
    print(f"{game}: best={max(scores)}, avg={sum(scores)/len(scores):.1f}")
```

### Analyzing Trajectories

The `trajectory.jsonl` files contain per-round structured records with fields:
- `round`, `tool`, `action`, `current_score`, `best_score`, `full_score`
- `observation`, `observation_before`, `feedback`
- `admissible_commands`, `done`, `won`, `lost`
- For `wiki_memory_read`: `query`, `total_matches`
- For `query_wm`: `total_nodes`, `total_edges`, `frontier_count`

### Comparison Plots

See `analysis/plot_glm52_only.py` and `analysis/plot_evo_vs_ours.py` for standalone plotting scripts with hardcoded data.

---

## Key Source Files

| File | Description |
|---|---|
| `agia.py` | Main agent execution engine (LLM interaction, tool dispatch, history compression) |
| `src/tool_executor.py` | Tool registration and dispatch; trajectory recording |
| `src/tools/tale_jericho_tools.py` | Jericho game tool: action execution, FATAL interception, loop detection, world model graph, query_wm |
| `src/wiki_memory.py` | Embedding-based semantic retrieval (wiki_memory_read); ablation logic |
| `apps/tale_jericho/run_all_tasks.py` | Experiment runner: orchestrates play+curation iterations, manages parallelism |
| `apps/tale_jericho/prompts/system_prompt.txt` | Play agent system prompt (SURVIVAL FIRST, strategy, wiki usage rules) |
| `apps/tale_jericho/prompts/phase_m_prompt.txt` | Curator prompt: knowledge rewrite rules, Evidence linking, FATAL tagging constraints |
| `apps/tale_jericho/prompts/tool_prompt.json` | Tool schema descriptions for the LLM |

---

## Reference Documents

| Document | Description |
|---|---|
| `ablation.md` | Full ablation study results (4 conditions × 6 games) |
| `wiki_evolve_paper.md` | Academic manuscript with system design and experimental results |
| `experiments.md` | Detailed experiment history across all rounds (abl1–abl19) |
| `data_readme.md` | Data archive structure and experiment-to-data mapping |
