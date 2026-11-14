# Handover Document for Future Coding Agents

> **Date**: 2026-08-05
> **Context**: This document captures all knowledge, hidden conventions, design decisions, and data locations accumulated during the development and experimentation of the Wiki-Evolve system across multiple sessions.
> **Repository**: https://github.com/agi-hub/AGIAgent_jericho (private)
> **Working directory (experiments)**: `/home/agiagent/AGIAgent_jericho/`
> **Clean code copy**: `/mnt/data/AGIAgent_jericho_glm52/`

---

## 1. System Overview

Wiki-Evolve is a test-time learning (TTL) framework for LLM agents playing Jericho text adventure games. It is built on top of the AGIAgent platform (`agia.py`), which is a general-purpose LLM agent executor with tool-calling, history compression, and multi-agent support.

The agent plays the same game $K=10$ times. Between each playthrough, a "curation phase" distills the trajectory into structured knowledge. The agent retrieves this knowledge during subsequent playthroughs to improve performance.

### Core Pipeline
```
Episode 1 (no memory) → Curation 1 → Episode 2 (uses memory) → Curation 2 → ... → Episode 10
```

---

## 2. Architecture — Three-Tier Memory

### Tier 1: Semantic Knowledge ($\mathcal{S}$)
- **Location**: `data/default/general/wiki/{experiment_name}/knowledge/score_recipe_{game}.md`
- **Format**: Markdown with YAML front-matter (`applies_to: [JerichoEnvGameName]`)
- **Sections**: Scoring Path (with `(Room) action → +score`), Death Traps (`[FATAL:keywords] (Room)`), Unexplored
- **Lifecycle**: Rewritten from scratch by the curator LLM each iteration (compress, don't append). Capped at 800 words.
- **Evidence links**: Each entry has `Evidence: [Attempt N](../experiences/DATE/gamename.md)` linking back to episodic records.

### Tier 2: Episodic Experience ($\mathcal{E}$)
- **Location**: `data/default/general/wiki/{experiment_name}/experiences/{YYYY-MM-DD}/{game}.md`
- **Format**: Append-only. One `## Attempt N` entry per episode with score, death cause, progress, key finding.
- **Lifecycle**: Never modified. Grows monotonically.
- **Date folder issue**: The date folder is `datetime.now()` at curation time. If an experiment spans midnight, multiple date folders may exist. The `_phase_m_requirement()` function injects the correct relative path into the curator's prompt.

### Tier 3: World Model Graph ($\mathcal{G}$)
- **Location**: In-memory only (`self._wm_graph` dict in `TaleJerichoTools`). Does NOT persist to disk.
- **Lifecycle**: Reset at the start of each playthrough (`session_started=True` → `self._wm_graph = {}`).
- **Query**: `query_wm()` tool returns text-formatted graph (rooms, edges, untried actions, frontier).
- **Building**: Updated automatically in `tale_jericho_action()` after each `env.step()`. Extracts room signature from observation first line. Tracks (action, room) pairs, score deltas, admissible commands.

---

## 3. Key Source Files and Their Roles

| File | What It Does | Critical Details |
|---|---|---|
| `agia.py` | Main agent executor | Manages LLM interaction rounds, tool dispatch, history compression. Entry point for all play and curation phases. |
| `src/tool_executor.py` | Tool registration & dispatch | Registers `tale_jericho_action`, `query_wm`, `wiki_memory_read`. Contains `_append_trajectory_record()` for JSONL logging. **Line 2433**: The set of logged tools — must include `"query_wm"`. |
| `src/tools/tale_jericho_tools.py` | Jericho game tool | **THE most important file.** Contains: action execution, FATAL interception, loop detection, world model graph, query_wm. ~890 lines. |
| `src/wiki_memory.py` | Semantic retrieval | Embedding-based search using BGE-M3. Contains ablation logic for no_wiki/no_knowledge/no_experiences modes. `_extract_relevant_snippet()` was removed — now returns full content (no truncation). `max_results` capped at 3 regardless of caller input. |
| `apps/tale_jericho/run_all_tasks.py` | Experiment runner | Orchestrates play+curation iterations. `_phase_m_requirement()` builds curator prompt. `_play_requirement()` builds play agent prompt. Sets env vars: `AGIA_WIKI_ROOT`, `JERICHO_ACTIVE_ENV`, `AGIA_WIKI_ABLATION`. |
| `apps/tale_jericho/prompts/system_prompt.txt` | Play agent system prompt | SURVIVAL FIRST section, wiki usage rules (max 3 queries, use as REFERENCE not script). |
| `apps/tale_jericho/prompts/phase_m_prompt.txt` | Curator prompt | Knowledge rewrite rules, Evidence link format, FATAL tagging rules ("Only mark FATAL on actions that NEVER score"), room labeling ("Room must be where agent EXECUTES the action"). |
| `apps/tale_jericho/prompts/tool_prompt.json` | Tool schema for LLM | Describes `tale_jericho_action`, `query_wm`, `wiki_memory_read`. Must be valid JSON. |
| `apps/tale_jericho/config.txt` | GLM-5.2 config | API key, base URL, model name. |
| `apps/tale_jericho_pro/config.txt` | DeepSeek-Pro config | Same structure, different API. |
| `apps/tale_jericho_gemini/config.txt` | Gemini config | `streaming=False` required (hallucination detector issue). `Tool_calling_format=False` required (unstable native tool calling). |

---

## 4. Hidden Conventions and Gotchas

### 4.1 Environment Variables (set by run_all_tasks.py)
- `AGIA_WIKI_ROOT` — Absolute path to wiki directory. Used by both `wiki_memory.py` and `tale_jericho_tools.py` (FATAL).
- `JERICHO_ACTIVE_ENV` — e.g., `JerichoEnvDetective`. Used for cross-game filtering in wiki_memory_read and game slug derivation.
- `AGIA_WIKI_ABLATION` — One of: `""`, `"no_wiki"`, `"no_knowledge"`, `"no_experiences"`, `"no_world_model"`.
- `AGIA_EXPERIMENT_NAMESPACE` — Experiment name, used for wiki path construction.

### 4.2 The `_obs_lines` Variable Bug (FIXED)
In `tale_jericho_tools.py`, the loop detection code uses `_obs_lines` to compute room signature. During the WM graph refactor, `_obs_lines` was accidentally moved inside the `if _ablation != "no_wiki":` block, causing `NameError` when ablation is active. **Fixed** by defining `_obs_lines` unconditionally before loop detection.

### 4.3 Gemini Compatibility
- `Tool_calling_format=True` + `streaming=True` → **185 hallucination false positives per play** (Gemini outputs "Tool execution results:" in its text, triggering the detector).
- `Tool_calling_format=True` + `streaming=False` → Some rounds Gemini outputs JSON text instead of using the tool_calls API field → actions not parsed → trajectory gaps.
- **Solution**: `Tool_calling_format=False` + `tool_call_parse_format=json` + `streaming=False` → Works correctly, all actions parsed.
- `enable_thinking=False` is also set for Gemini.

### 4.4 FATAL Interception — Multiple Edge Cases
1. **Scoring actions never FATAL**: The code checks if the FATAL keyword appears in any scoring line (`->` + `+`). If so, the FATAL entry is skipped entirely.
2. **Room matching threshold**: `len(w) >= 3` (not `> 3`) — "Bar" (3 chars) must match.
3. **Room unknown (`room=""`)**: Navigation words (north/south/east/west/up/down) are SKIPPED to prevent over-blocking. Non-navigation FATAL entries (say manaz, fwoosh) are TRUSTED and blocked.
4. **FATAL room label**: The prompt instructs curator to label the EXECUTION room (where agent is when it performs the action), not the DESTINATION room (where death occurs). This was a recurring source of mismatch.

### 4.5 Loop Detection — Action@Room (not Action-only)
Old logic: count action text frequency in 10-step window → 100% false positive rate (308 triggers, all false). New logic: count `(action, room_signature)` pairs → only true loops detected. Room signature = first line of observation text, first 50 chars.

### 4.6 wiki_memory_read — Full Content Return
The `_extract_relevant_snippet()` function was removed. Now `wiki_memory_read` returns the **complete file content** for each matched page. This was done because the 200-char snippet truncation caused agents to bypass it by `cat`-ing the file directly (54% of plays).

### 4.7 The `pro` App is a sed Copy
`apps/tale_jericho_pro/` is a copy of `apps/tale_jericho/` with `APP_NAME="tale_jericho_pro"` and `TOOL_PREFIX="tale_jericho"`. It was created by `sed`, not a symlink. **The phase_m_prompt.txt was NOT synced** until August 2026 — Pro experiments before abl16 had 0 Evidence links because the old prompt was used.

### 4.8 Tales Library Import Warnings
`tales/__init__.py` tries to import alfworld and textworld_express, which are not installed. This produces verbose warnings on every startup. **Fixed** by silently skipping these in `tales/__init__.py` (line 49-52: check for module name in exception string, `continue` if match).

### 4.9 Phase Records JSON Format
`phase_records.json` is a **flat list** of iteration dicts (not nested under an `iterations` key). Each dict has `play_current_score`, `play_best_score`, `play_full_score`, `play_status`, etc.

### 4.10 Score Sanitization
`_sanitize_score()` in `tale_jericho_tools.py` guards against transient invalid scores (e.g., restart confirmation screens). If the raw score decreases from the previous best, it's clamped.

---

## 5. Experiment Data Locations

### 5.1 Benchmark Results (trajectories, scores, logs)
```
data/benchmark_results/{experiment_name}/outputs/
  output_{app}_{idx}_{EnvName}_play{N}_{timestamp}/logs/
    trajectory.jsonl    ← Per-round structured log
    manager.log         ← Full reasoning trace
    manager.out         ← Terminal output
    score_summary.json  ← Final scores
    agia.log            ← System init
  output_{app}_{idx}_{EnvName}_phasem{N}_{timestamp}/logs/
    (same structure)
  output_{app}_{idx}_{EnvName}_phase_records.json
    ← Per-game summary of all 10 iterations
```

### 5.2 Wiki (knowledge + experience)
```
data/default/general/wiki/{experiment_name}/
  knowledge/score_recipe_{game}.md
  experiences/{date}/{game}.md
  .wiki_index.npz    ← BGE-M3 embedding index (binary, auto-generated)
```

### 5.3 Experiment Index

| Experiment | Model | Condition | Games | Status |
|---|---|---|---|---|
| abl19_glm52_full | GLM-5.2 | Full | 6 (Det,Lib,Zork1,Zork3,Bal,Temple) | ✅ Complete |
| abl19_glm52_no_wiki | GLM-5.2 | Naive ReAct | 6 | ✅ Complete |
| abl19_glm52_no_wiki_wm | GLM-5.2 | World Model only | 6 | ✅ Complete |
| abl19_glm52_no_knowledge | GLM-5.2 | Exp+WM, no Knowledge | 6 | ✅ Complete |
| abl16_pro_full | DeepSeek-Pro | Full | 9 (above 6 + Deephome, Murdac, Advent) | ✅ Complete |
| abl18_gemini_full | Gemini-Flash | Full | 6 | ✅ Complete |
| abl18_gemini_test2 | Gemini-Flash | Zork1 rerun | 1 (Zork1) | ✅ Complete |
| abl15_glm_full | GLM-4.7 | Full | 9 | ✅ Complete (older code version) |
| abl14_glm_no_wiki | GLM-4.7 | Naive ReAct | 9 | ✅ Complete (older code version) |
| abl17_glm_full | GLM-4.7 | Full | 12 new games | ✅ Complete |
| abl17_glm_full_rerun | GLM-4.7 | FATAL fix rerun | 5 games | ✅ Partial |

### 5.4 Baseline Data
- **EvoTest (GLM-5.2)**: `/mnt/data/EvoTest/logs/run_6games_20260802-121608_results.md`
- **Other baselines (Gemini)**: `compare/comparison_data.csv` and `compare/figure2_data.csv` (wide format, 50 episodes)
- **Comparison Excel**: `compare/comparison_data.xlsx`

### 5.5 Generated Figures
- `compare/comparison_glm52_only.png/pdf` — GLM-5.2 vs all baselines (plot script: `compare/plot_glm52_only.py`)
- `compare/comparison_evo_vs_ours.png/pdf` — GLM-5.2 + DeepSeek-Pro vs baselines (plot script: `compare/plot_evo_vs_ours.py`)
- `compare/comparison_figure_full.png/pdf` — All models (including GLM-4.7) vs baselines, 50 episodes

### 5.6 Key Documents
- `ablation.md` — Full 4-condition ablation study with FATAL counterfactual
- `wiki_evolve_paper.md` — Academic manuscript (with SVG figures)
- `experiments.md` — Full experiment history (abl1–abl19)
- `gemini_results.md` — Gemini cross-model comparison
- `abl16_results.md` — DeepSeek-Pro results
- `data_readme.md` — Data archive mapping

---

## 6. API Credentials

All API keys are stored in the respective `config.txt` files:

| Model | Config File | API Base |
|---|---|---|
| GLM-5.2 / GLM-4.7 | `apps/tale_jericho/config.txt` | `https://open.bigmodel.cn/api/coding/paas/v4/` |
| DeepSeek-Pro | `apps/tale_jericho_pro/config.txt` | `https://api.deepseek.com/anthropic` |
| Gemini-Flash | `apps/tale_jericho_gemini/config.txt` | `https://xinchenbuqi3776.zeabur.app/v1` |
| Embedding (BGE-M3) | All configs | `https://api.siliconflow.cn/v1` |

---

## 7. Known Issues and Future Work

### 7.1 Room Disambiguation
Some games have multiple rooms with the same name (e.g., Detective has multiple "Outside" locations). The knowledge file cannot distinguish them, leading to:
- Ambiguous scoring path instructions
- FATAL over-blocking or under-blocking

**Potential fix**: Enrich room signatures with distinguishing features (e.g., visible objects, exits).

### 7.2 World Model Not Persisted Across Episodes
The current design resets $\mathcal{G}$ each episode. This prevents cross-episode spatial accumulation. A persistent graph could enable the agent to resume exploration from known frontiers.

### 7.3 Experience Retrieval Low Signal-to-Noise
Without semantic knowledge, agents querying episodic experience get raw trajectory summaries that are hard to act on. The experience tier needs better structuring (e.g., per-room action outcomes) to be useful independently.

### 7.4 FATAL Cannot Model Conditional Deaths
Deaths that depend on game state (e.g., "examine writing is safe first time but fatal after placing items") cannot be captured by the current binary FATAL tag. The scoring-action exclusion heuristic helps but is imperfect.

### 7.5 Gemini API Instability
The Gemini proxy (`xinchenbuqi3776.zeabur.app`) occasionally returns 500 ("当前无可用凭证"). This is a server-side credential pool issue, not a code problem. Retries are built into agia.py (3 attempts with backoff).

### 7.6 Pro App Prompt Sync
`apps/tale_jericho_pro/prompts/phase_m_prompt.txt` was synced from `apps/tale_jericho/` on 2026-08-02. Any future prompt changes must be manually synced to the pro app (or automate with a symlink).

---

## 8. How to Reproduce Key Results

### 8.1 GLM-5.2 Full (best result)
```bash
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 2 \
  --experiment-name reproduce_glm52_full
```

### 8.2 Naive ReAct Baseline
```bash
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 2 \
  --experiment-name reproduce_no_wiki \
  --ablation no_wiki
```

### 8.3 Check Results
```python
import json, glob
prefix = "reproduce_glm52_full"
for game in ['Detective','Library','Zork1','Zork3','Balances','Temple']:
    f = glob.glob(f'data/benchmark_results/{prefix}/outputs/*{game}*phase_records.json')[0]
    data = json.load(open(f))
    scores = [float(it.get('play_current_score',0) or 0) for it in data if isinstance(it, dict)]
    print(f"{game}: avg={sum(scores)/len(scores):.1f} best={max(scores):.0f}")
```

---

## 9. Disk Space Management

The experiment data grows fast (~30-35MB per 6-game × 10-iteration experiment). Key space consumers:
- `data/default/general/experience/` — Curation phase LLM interaction logs (can be very large, e.g., 26MB for a single run_all_tasks log)
- `data/benchmark_results/*/outputs/*/logs/manager.log` — Full reasoning traces

Cleanup approach:
```bash
# Remove experience logs (keep wiki knowledge + experience files)
rm -rf data/default/general/experience/{experiment_name}/logs/

# Remove old experiment benchmark data
rm -rf data/benchmark_results/{old_experiment_name}/
```

Current disk: 49G total, ~33G used (as of 2026-08-05).

---

## 10. Quick Reference — Environment Setup

```bash
# Python environment
source /home/agiagent/venv_biagentsci/bin/activate

# Tale-Suite path
export PYTHONPATH=/home/agiagent/tale-suite:$PYTHONPATH

# Or agia.py handles this via _resolve_tale_suite_root()
# Default search path: /home/agiagent/tale-suite
```

The `tale-suite` package provides the `tales` module which wraps Jericho games via `gymnasium`. The Jericho game files (`.z5`, `.z3`) are downloaded on demand from GitHub by `tales.jericho_data.prepare_jericho_data()`.
