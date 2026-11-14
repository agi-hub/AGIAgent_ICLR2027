# tale_jericho

TALE-Suite Jericho app for `AGIAgent`, using the **wiki memory system** (three-phase pipeline).

## Architecture

```
phase1_explore (solve task) → phase_m (curate wiki) → phase2_solve (use wiki)
```

- **phase1**: Agent solves the task using `tale_jericho_action`. No memory tools. Trajectory is logged to `logs/trajectory.jsonl`.
- **phase_m**: After phase1, a separate agent session reads the trajectory log and updates the wiki with new knowledge. Uses `run_terminal_cmd` (to read/write wiki files) and `wiki_memory_read` (to search existing wiki).
- **phase2**: Agent solves a fresh episode using `tale_jericho_action` + `wiki_memory_read` (grep-based search over wiki).

## Wiki Structure

```
data/default/general/wiki/<experiment_name>/
├── knowledge/           # Skills, recipes, tactics
├── experiences/         # Key lessons by date (YYYY-MM-DD/)
└── world_model/
    ├── locations/       # Room/scene pages
    └── objects/         # Object pages
```

Pages are Markdown with optional YAML front-matter (`applies_to`, `sources`).

## Tools

| Tool | Phases | Description |
|---|---|---|
| `tale_jericho_action` | 1, 2 | Execute one Jericho action |
| `wiki_memory_read` | M, 2 | Grep search over wiki .md files |
| `run_terminal_cmd` | M | Read/write wiki files via shell |

## Run One Session

```bash
cd /path/to/AGIAgent_wiki
python agia.py --app tale_jericho
```

## Run Benchmark (full pipeline)

```bash
cd /path/to/AGIAgent_wiki

# Full pipeline: phase1 → phase_m → phase2 for selected tasks
python apps/tale_jericho/run_all_tasks.py \
  --task-list "[1,2,3]" \
  --explore-loops 200 \
  --phase-m-loops 15 \
  --solve-loops 100 \
  --parallel-tasks 2 \
  --experiment-name jericho_wiki_v1

# Disable phase_m
python apps/tale_jericho/run_all_tasks.py --phase-m-loops 0 ...

# Phase 1 only (produce wiki assets without solving)
python apps/tale_jericho/run_all_tasks.py --phase1-only ...

# Baseline (no memory, single-phase solve)
python apps/tale_jericho/run_all_tasks.py --baseline ...
```

Output:
- benchmark results in `data/benchmark_results/<experiment_name>/`
- long logs in `data/default/general/experience/<experiment_name>/logs/`

## Key Files

- `src/wiki_memory.py` — WikiMemoryReader (wiki_memory_read tool)
- `src/tool_executor.py` — Tool registration + trajectory.jsonl recording (phase_m consumption)
- `src/tools/tale_jericho_tools.py` — Jericho environment wrapper (`tale_jericho_action`)
- `apps/tale_jericho/prompts/phase_m_prompt.txt` — Phase M system prompt
- `apps/tale_jericho/prompts/system_prompt.txt` — Phase 1/2 system prompt
- `apps/tale_jericho/prompts/tool_prompt.json` — Tool schema (3 tools)
- `apps/tale_jericho/run_all_tasks.py` — Runner with phase1→phase_m→phase2 pipeline
