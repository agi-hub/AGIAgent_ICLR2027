# ScienceWorld Wiki Memory System

## Architecture

ScienceWorld uses a **wiki-based memory system** with three phases:

```
phase1_explore (solve task) → phase_m (curate wiki) → phase2_solve (use wiki)
```

- **phase1**: Agent solves the task using `scienceworld_action`. No memory tools. Trajectory is logged to `manager.log`.
- **phase_m**: After phase1, a separate agent session reads the trajectory log and updates the wiki with new knowledge. Uses `terminal` (to read/write wiki files) and `wiki_memory_read` (to search existing wiki).
- **phase2**: Agent solves a fresh episode using `scienceworld_action` + `wiki_memory_read` (grep-based search over wiki).

## Wiki Structure

```
data/default/general/wiki/<experiment_name>/
├── knowledge/           # Skills, recipes, tactics
├── experiences/         # Key lessons by date (YYYY-MM-DD/)
└── world_model/
    ├── locations/       # Room pages
    └── objects/         # Object pages
```

Pages are Markdown with optional YAML front-matter (`applies_to`, `sources`).

## Tools

| Tool | Phases | Description |
|---|---|---|
| `scienceworld_action` | 1, 2 | Execute one ScienceWorld action |
| `wiki_memory_read` | M, 2 | Grep search over wiki .md files |
| `terminal` | M | Read/write wiki files via shell |

## Running

```bash
# Full pipeline: phase1 → phase_m → phase2
python apps/scienceworld/run_all_tasks.py \
  --selection-mode fixed_total \
  --fixed-dataset-split total \
  --explore-loops 200 \
  --phase-m-loops 15 \
  --solve-loops 100 \
  --parallel-tasks 2 \
  --experiment-name scienceworld_wiki_v1

# Disable phase_m
python apps/scienceworld/run_all_tasks.py --phase-m-loops 0 ...

# Phase 1 only
python apps/scienceworld/run_all_tasks.py --phase1-only ...
```

## Key Files

- `src/wiki_memory.py` — WikiMemoryReader (grep-based wiki_memory_read tool)
- `src/tool_executor.py` — Tool registration (scienceworld_action + wiki_memory_read)
- `src/tools/scienceworld_tools.py` — ScienceWorldEnv wrapper
- `apps/scienceworld/prompts/phase_m_prompt.txt` — Phase M system prompt
- `apps/scienceworld/prompts/system_prompt.txt` — Phase 1/2 system prompt
- `apps/scienceworld/run_all_tasks.py` — Runner with phase1→phase_m→phase2 pipeline

## Testing

```bash
python -m unittest tests.test_scienceworld_entry
```

## What was removed (from previous biagent system)

- `src/biagent/` — entire directory (curiosity pipeline, scene builder, world/skill graph managers)
- `src/skill_evolve/` — entire directory (skill tools, graph skill, world model tools)
- All curiosity/skill/memory tools from tool_executor.py (~1600 lines)
- Old data directories: biagent_memory/, graph_experience/, world_model_graph/, experience/, _curiosity_runtime/
- Old prompts: memory_tools.json, graph_skill_prompts.yaml, world_model_prompts.yaml, scene_reflection_prompts.yaml
- WUE evaluator and related files
