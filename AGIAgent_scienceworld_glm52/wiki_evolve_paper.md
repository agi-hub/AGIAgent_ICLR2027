# Wiki-Evolve: A Persistent Memory Framework for Gradient-Free Test-Time Learning in Text Adventure Games

## Abstract

We present Wiki-Evolve, a gradient-free test-time learning (TTL) framework that enables large language model (LLM) agents to progressively improve their performance across repeated playthroughs of text adventure games. Unlike prior approaches that treat memory as a flat cache of successes and failures, Wiki-Evolve organizes agent experience into a structured, three-tier persistent memory: (1) *semantic knowledge* — distilled scoring recipes and death traps in natural language; (2) *episodic experience* — verbatim append-only records of each playthrough; and (3) a *world model graph* — an in-memory spatial representation tracking room connectivity, explored actions, and frontier candidates. A dedicated curation phase, interleaved between playthroughs, compresses raw trajectories into actionable knowledge while maintaining bidirectional links to their evidentiary origins. We further introduce two safety mechanisms: a *hard protection layer* that blocks actions tagged as unconditionally fatal, and a *loop detector* that identifies behavioral stagnation through action–location pair analysis. Experiments on six Jericho games with GLM-5.2 demonstrate that the full system achieves 58.3% normalized average score, compared to 33.6% for a memoryless baseline — a 73% relative improvement. Ablation studies isolate the contributions of each component, revealing that semantic knowledge and hard protection together account for 96% of the total gain.

---

## 1. Introduction

Text adventure games (interactive fiction) pose a unique challenge for LLM-based agents: they require long-horizon planning, precise natural language comprehension, exploration of branching narratives, and avoidance of irreversible fatal traps — all under sparse reward signals. A single misstep can terminate the game, zeroing all accumulated progress.

Test-time learning (TTL) offers a promising paradigm: rather than updating model weights, the agent iteratively refines its behavioral strategy through accumulated experience on the same task. Each playthrough generates a trajectory of observations, actions, and outcomes; between playthroughs, the agent distills this raw experience into actionable knowledge that guides future attempts.

Existing TTL approaches for LLM agents typically employ unstructured memory — flat lists of successes, failures, or free-form reflections. While effective for short games, these representations suffer from three limitations in complex text adventures:

1. **Scaling inefficiency**: As experience accumulates, flat memories become noisy and difficult to retrieve relevant information from.
2. **Absence of spatial reasoning**: Text adventures are inherently spatial — the same action (e.g., "go north") has different consequences depending on the room. Flat memories cannot capture this location-dependence.
3. **No safety guarantees**: Agents repeatedly fall into known death traps because reflective warnings are too soft to override the model's action generation.

Wiki-Evolve addresses these limitations through a structured memory architecture with three tiers, a dedicated curation mechanism, and safety enforcement layers. The framework is entirely gradient-free and model-agnostic — it operates purely through prompt engineering, tool interfaces, and file-based persistence.

---

## 2. System Architecture

### 2.1 Overview

The Wiki-Evolve framework operates in an iterative pipeline: for each game, the agent performs $K$ playthroughs (episodes), interleaved with $K-1$ curation phases that update the persistent memory between episodes.

```
Episode 1 → Curation 1 → Episode 2 → Curation 2 → ... → Episode K
```

During each episode, the agent interacts with the game environment through a single action tool, consulting the persistent memory as needed. During each curation phase, a curator agent (driven by the same LLM) analyzes the completed trajectory and updates the memory artifacts.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 380" font-family="Helvetica, Arial, sans-serif">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#555"/></marker>
    <marker id="arrowR" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#c0392b"/></marker>
  </defs>
  <rect x="20" y="30" width="160" height="320" rx="10" fill="#eaf2fb" stroke="#2980b9" stroke-width="2"/>
  <text x="100" y="55" text-anchor="middle" font-size="14" font-weight="bold" fill="#2980b9">Play Phase</text>
  <rect x="40" y="75" width="120" height="28" rx="5" fill="#fff" stroke="#2980b9"/><text x="100" y="93" text-anchor="middle" font-size="11">LLM Backbone</text>
  <rect x="40" y="115" width="120" height="28" rx="5" fill="#fff" stroke="#2980b9"/><text x="100" y="133" text-anchor="middle" font-size="11">tale_jericho_action</text>
  <rect x="40" y="155" width="120" height="28" rx="5" fill="#fff" stroke="#2980b9"/><text x="100" y="173" text-anchor="middle" font-size="11">wiki_memory_read</text>
  <rect x="40" y="195" width="120" height="28" rx="5" fill="#fff" stroke="#2980b9"/><text x="100" y="213" text-anchor="middle" font-size="11">query_wm</text>
  <rect x="40" y="245" width="120" height="28" rx="5" fill="#fff" stroke="#2980b9"/><text x="100" y="263" text-anchor="middle" font-size="11">Game Environment</text>
  <rect x="40" y="290" width="120" height="28" rx="5" fill="#fff" stroke="#2980b9"/><text x="100" y="308" text-anchor="middle" font-size="11">Trajectory Log</text>
  <rect x="260" y="30" width="160" height="270" rx="10" fill="#fdf2e9" stroke="#e67e22" stroke-width="2"/>
  <text x="340" y="55" text-anchor="middle" font-size="14" font-weight="bold" fill="#e67e22">Curation Phase</text>
  <rect x="280" y="75" width="120" height="28" rx="5" fill="#fff" stroke="#e67e22"/><text x="340" y="93" text-anchor="middle" font-size="11">LLM Curator</text>
  <rect x="280" y="115" width="120" height="28" rx="5" fill="#fff" stroke="#e67e22"/><text x="340" y="133" text-anchor="middle" font-size="11">Trajectory Analysis</text>
  <rect x="280" y="155" width="120" height="28" rx="5" fill="#fff" stroke="#e67e22"/><text x="340" y="173" text-anchor="middle" font-size="11">Knowledge Rewrite</text>
  <rect x="280" y="195" width="120" height="28" rx="5" fill="#fff" stroke="#e67e22"/><text x="340" y="213" text-anchor="middle" font-size="11">Experience Append</text>
  <rect x="280" y="235" width="120" height="28" rx="5" fill="#fff" stroke="#e67e22"/><text x="340" y="253" text-anchor="middle" font-size="11">Evidence Linking</text>
  <rect x="500" y="30" width="180" height="320" rx="10" fill="#eafaf1" stroke="#27ae60" stroke-width="2"/>
  <text x="590" y="55" text-anchor="middle" font-size="14" font-weight="bold" fill="#27ae60">Persistent Memory</text>
  <rect x="520" y="70" width="140" height="80" rx="5" fill="#fff" stroke="#27ae60"/>
  <text x="590" y="90" text-anchor="middle" font-size="12" font-weight="bold">Semantic Knowledge (S)</text>
  <text x="590" y="108" text-anchor="middle" font-size="10">Scoring Path</text>
  <text x="590" y="123" text-anchor="middle" font-size="10">Death Traps [FATAL]</text>
  <text x="590" y="138" text-anchor="middle" font-size="10">Unexplored</text>
  <rect x="520" y="165" width="140" height="60" rx="5" fill="#fff" stroke="#27ae60"/>
  <text x="590" y="185" text-anchor="middle" font-size="12" font-weight="bold">Episodic Experience (E)</text>
  <text x="590" y="202" text-anchor="middle" font-size="10">Append-only Records</text>
  <text x="590" y="217" text-anchor="middle" font-size="10">Links → S</text>
  <rect x="520" y="240" width="140" height="60" rx="5" fill="#fff" stroke="#27ae60"/>
  <text x="590" y="260" text-anchor="middle" font-size="12" font-weight="bold">World Model Graph (G)</text>
  <text x="590" y="277" text-anchor="middle" font-size="10">Room Connectivity</text>
  <text x="590" y="292" text-anchor="middle" font-size="10">Frontier Actions</text>
  <rect x="740" y="30" width="140" height="110" rx="10" fill="#fdedec" stroke="#c0392b" stroke-width="2"/>
  <text x="810" y="52" text-anchor="middle" font-size="13" font-weight="bold" fill="#c0392b">Safety Layer</text>
  <rect x="760" y="65" width="100" height="24" rx="5" fill="#fff" stroke="#c0392b"/><text x="810" y="81" text-anchor="middle" font-size="10">FATAL Intercept</text>
  <rect x="760" y="100" width="100" height="24" rx="5" fill="#fff" stroke="#c0392b"/><text x="810" y="116" text-anchor="middle" font-size="10">Loop Detector</text>
  <line x1="180" y1="130" x2="260" y2="130" stroke="#555" stroke-width="1.5" marker-end="url(#arrow)"/>
  <text x="220" y="122" text-anchor="middle" font-size="9">trajectory</text>
  <line x1="420" y1="170" x2="500" y2="110" stroke="#555" stroke-width="1.5" marker-end="url(#arrow)"/>
  <text x="465" y="135" text-anchor="middle" font-size="9">writes</text>
  <line x1="500" y1="110" x2="180" y2="170" stroke="#555" stroke-width="1.5" stroke-dasharray="4,3" marker-end="url(#arrow)"/>
  <text x="340" y="162" text-anchor="middle" font-size="9">retrieves</text>
  <line x1="740" y1="77" x2="180" y2="133" stroke="#c0392b" stroke-width="1.5" stroke-dasharray="2,2" marker-end="url(#arrowR)"/>
  <text x="460" y="68" text-anchor="middle" font-size="9" fill="#c0392b">intercepts</text>
</svg>

**Figure 1.** System architecture of Wiki-Evolve. The Play Phase (left) interacts with the game environment and consults the Persistent Memory (right). The Curation Phase (center) distills trajectory data into structured knowledge. The Safety Layer intercepts fatal actions and detects behavioral loops.

### 2.2 Three-Tier Memory Architecture

The persistent memory $M$ is organized into three tiers, each serving a distinct function:

#### Tier 1: Semantic Knowledge ($\mathcal{S}$)

The semantic knowledge tier stores *distilled, actionable rules* in natural language. It is maintained as a structured markdown file per game, containing three sections:

- **Scoring Path**: Location-annotated action sequences that reliably increase score, formatted as `(Room) action → +Δscore`. Each entry is linked to its originating episode(s) via evidence citations.
- **Death Traps**: Actions tagged as `[FATAL:keywords]` that unconditionally lead to game termination, annotated with the room in which they are lethal.
- **Unexplored**: Known obstacles, unsolved puzzles, and candidates for future exploration.

The knowledge file is *rewritten from scratch* at each curation phase — the curator merges prior knowledge with new observations, producing a compressed representation capped at 800 words. This rewrite-rather-than-append design prevents knowledge bloat and ensures the representation remains concise and retrievable.

#### Tier 2: Episodic Experience ($\mathcal{E}$)

The episodic tier maintains *verbatim, append-only records* of each playthrough. After each episode, the curator appends a structured entry:

```
## Attempt N (score X/Y, Z moves, outcome)
- Died at: action at Room (cause)    [if applicable]
- Progress: reached score X, explored N rooms
- Key finding: one-sentence summary
```

These records serve as the evidentiary basis for knowledge distillation. They are never modified or compressed — each entry preserves the full context of a specific attempt. Crucially, every entry in the semantic knowledge tier cites its originating experience record via a relative markdown link (e.g., `Evidence: [Attempt 3](../experiences/2026-08-01/detective.md)`), creating a *bidirectional traceability link* between distilled rules and raw evidence.

#### Tier 3: World Model Graph ($\mathcal{G}$)

The world model is an *in-memory, per-episode spatial representation* that tracks the agent's evolving understanding of the game environment. It is constructed incrementally during gameplay, without requiring any curation phase.

Each node in the graph represents a room or location, identified by a *room signature* extracted from the observation text (typically the first line of the game's textual response). Each node maintains:

- **Tried actions**: The set of actions executed in this room and their outcomes (scored, moved, died, no effect).
- **Edges**: Directed transitions to other rooms, annotated with the triggering action and score delta.
- **Frontier set**: The set of admissible commands not yet attempted in this room — i.e., *unexplored action candidates*.
- **Visit count**: How many times the agent has been in this room.

The world model is queried via a dedicated tool (`query_wm`) that returns a formatted text representation of the graph, highlighting frontier nodes with unexplored actions. This enables the agent to systematically identify where exploration opportunities remain, rather than relying on memory of prior observations that may have been lost to context compression.

The graph is *episode-scoped* — it is reset at the start of each playthrough and does not persist across episodes. This design reflects the exploratory nature of each playthrough: the agent builds a fresh map each time, using semantic knowledge to guide where to go and the world model to track where it has been.

### 2.3 Memory Retrieval

The agent accesses persistent memory through two channels:

**Semantic retrieval** (`wiki_memory_read`): An embedding-based semantic search over the knowledge and experience files. The agent issues natural-language queries (e.g., "detective score actions walkthrough"), and the system returns the top-$k$ matching passages ranked by cosine similarity to a BGE-M3 embedding of the query. Cross-game filtering deprioritizes entries from other games. Retrieval is rate-limited to 3 queries per episode to encourage strategic information-seeking rather than brute-force lookups.

**Direct world model query** (`query_wm`): Returns the current spatial graph in text format, including room connectivity, explored actions, and frontier candidates. This channel requires no semantic matching — it provides a complete snapshot of the agent's spatial knowledge.

### 2.4 Bidirectional Knowledge–Experience Links

A novel feature of Wiki-Evolve is the explicit *traceability link* between semantic knowledge entries and their episodic evidence. During curation, the curator is instructed to annotate every factual claim in the knowledge file with an evidence citation:

```
(Room) action → +Δscore. Evidence: [Attempt N](../experiences/DATE/gamename.md)
```

This serves two purposes:

1. **Verifiability**: A human researcher (or the curator itself in subsequent iterations) can trace any knowledge claim back to the specific trajectory that produced it, enabling error detection and correction.
2. **Provenance tracking**: When the curator rewrites the knowledge file, it can consult linked experiences to verify whether a rule still holds or has been contradicted by newer evidence.

---

## 3. Iterative Curation and Knowledge Evolution

### 3.1 The Curation Phase (Phase M)

Between episodes, a dedicated curation agent processes the completed trajectory and updates the memory. The curation agent receives:

1. The full structured trajectory log (actions, observations, scores, outcomes) from the just-completed episode.
2. A pre-extracted summary of score-changing actions (auto-generated from the trajectory to reduce the curator's parsing burden).
3. The file paths for the knowledge and experience files.
4. The relative path for evidence links (pre-computed to avoid path construction errors).

The curator performs three operations:

**Experience append**: A new entry is appended to the experience file, recording the episode's outcome, progress, and key finding.

**Knowledge rewrite**: The knowledge file is rewritten from scratch, merging prior knowledge with new observations. The curator is instructed to produce a location-annotated, action-oriented representation under 800 words. This rewrite-from-scratch design ensures that contradictory or outdated information is resolved, rather than accumulating across iterations.

**Evidence linking**: Each entry in the rewritten knowledge file is annotated with evidence citations linking back to the specific experience entries that support it.

### 3.2 Knowledge Evolution Dynamics

The knowledge file evolves across iterations in a *compress-and-refine* cycle:

- **Early iterations** (1–3): Knowledge is sparse and exploratory — the scoring path may be incomplete, and many rooms are listed as unexplored.
- **Middle iterations** (4–6): As the agent discovers more scoring actions, the scoring path grows longer and more precise. Death traps are identified and tagged. Unexplored items are resolved or reclassified.
- **Late iterations** (7–10): Knowledge stabilizes — the scoring path is complete, death traps are well-documented, and the focus shifts to edge cases and optimization.

This progressive refinement mirrors the way a human player internalizes a game's mechanics through repeated play: initial exploration builds a rough map, subsequent attempts fill in gaps and correct misconceptions, and final iterations focus on perfecting execution.

---
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 200" font-family="Helvetica, Arial, sans-serif">
  <defs>
    <marker id="arr" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#555"/></marker>
  </defs>
  <!-- Episode 1 -->
  <rect x="10" y="60" width="80" height="80" rx="8" fill="#eaf2fb" stroke="#2980b9" stroke-width="2"/>
  <text x="50" y="90" text-anchor="middle" font-size="12" font-weight="bold" fill="#2980b9">Episode 1</text>
  <text x="50" y="108" text-anchor="middle" font-size="10">Play</text>
  <text x="50" y="122" text-anchor="middle" font-size="10">(no memory)</text>
  <!-- Curation 1 -->
  <rect x="110" y="70" width="70" height="60" rx="8" fill="#fdf2e9" stroke="#e67e22" stroke-width="2"/>
  <text x="145" y="95" text-anchor="middle" font-size="11" font-weight="bold" fill="#e67e22">Curation</text>
  <text x="145" y="112" text-anchor="middle" font-size="10">Distill</text>
  <!-- Memory -->
  <rect x="200" y="65" width="60" height="70" rx="8" fill="#eafaf1" stroke="#27ae60" stroke-width="2" stroke-dasharray="3,2"/>
  <text x="230" y="95" text-anchor="middle" font-size="10" font-weight="bold" fill="#27ae60">S+E</text>
  <text x="230" y="112" text-anchor="middle" font-size="9">v1</text>
  <!-- Episode 2 -->
  <rect x="280" y="60" width="80" height="80" rx="8" fill="#eaf2fb" stroke="#2980b9" stroke-width="2"/>
  <text x="320" y="90" text-anchor="middle" font-size="12" font-weight="bold" fill="#2980b9">Episode 2</text>
  <text x="320" y="108" text-anchor="middle" font-size="10">Play</text>
  <text x="320" y="122" text-anchor="middle" font-size="10">(uses S+E)</text>
  <!-- Curation 2 -->
  <rect x="380" y="70" width="70" height="60" rx="8" fill="#fdf2e9" stroke="#e67e22" stroke-width="2"/>
  <text x="415" y="95" text-anchor="middle" font-size="11" font-weight="bold" fill="#e67e22">Curation</text>
  <text x="415" y="112" text-anchor="middle" font-size="10">Refine</text>
  <!-- Memory v2 -->
  <rect x="470" y="65" width="60" height="70" rx="8" fill="#eafaf1" stroke="#27ae60" stroke-width="2" stroke-dasharray="3,2"/>
  <text x="500" y="95" text-anchor="middle" font-size="10" font-weight="bold" fill="#27ae60">S+E</text>
  <text x="500" y="112" text-anchor="middle" font-size="9">v2</text>
  <!-- Episode 3 -->
  <rect x="550" y="60" width="80" height="80" rx="8" fill="#eaf2fb" stroke="#2980b9" stroke-width="2"/>
  <text x="590" y="90" text-anchor="middle" font-size="12" font-weight="bold" fill="#2980b9">Episode 3</text>
  <text x="590" y="108" text-anchor="middle" font-size="10">Play</text>
  <text x="590" y="122" text-anchor="middle" font-size="10">(uses S+E)</text>
  <!-- Dots -->
  <text x="670" y="100" text-anchor="middle" font-size="20" fill="#555">···</text>
  <!-- Episode K -->
  <rect x="700" y="60" width="80" height="80" rx="8" fill="#eaf2fb" stroke="#2980b9" stroke-width="2"/>
  <text x="740" y="90" text-anchor="middle" font-size="12" font-weight="bold" fill="#2980b9">Episode K</text>
  <text x="740" y="108" text-anchor="middle" font-size="10">Play</text>
  <text x="740" y="122" text-anchor="middle" font-size="10">(uses S+E)</text>
  <!-- Final Memory -->
  <rect x="810" y="65" width="70" height="70" rx="8" fill="#eafaf1" stroke="#27ae60" stroke-width="2"/>
  <text x="845" y="92" text-anchor="middle" font-size="10" font-weight="bold" fill="#27ae60">S+E</text>
  <text x="845" y="109" text-anchor="middle" font-size="9">final</text>
  <!-- Arrows -->
  <line x1="90" y1="100" x2="110" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="180" y1="100" x2="200" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="260" y1="100" x2="280" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="360" y1="100" x2="380" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="450" y1="100" x2="470" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="530" y1="100" x2="550" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="630" y1="100" x2="700" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="780" y1="100" x2="810" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <!-- Label -->
  <text x="450" y="170" text-anchor="middle" font-size="12" fill="#555">Iterative refinement: each episode's trajectory is distilled into progressively refined knowledge (S) and accumulated experience (E)</text>
  <text x="450" y="188" text-anchor="middle" font-size="11" fill="#999">Episode 1 uses no prior memory; episodes 2–K retrieve and leverage S+E during play</text>
</svg>

**Figure 2.** Iterative pipeline. Each playthrough (Episode) generates a trajectory that is processed by the Curation phase into updated knowledge ($\mathcal{S}$) and appended experience ($\mathcal{E}$). The world model ($\mathcal{G}$) is built fresh each episode (not shown). Evidence links connect $\mathcal{S}$ entries to their supporting $\mathcal{E}$ records.

## 4. Safety Mechanisms

### 4.1 Hard Protection (FATAL Interception)

Text adventure games frequently contain *irreversible fatal actions* — a single wrong move can terminate the game and zero all progress. While the semantic knowledge tier warns the agent about these actions in natural language, LLM-based agents do not reliably obey such soft constraints, particularly when the fatal action appears plausible within the current puzzle context.

Wiki-Evolve implements a *hard protection layer* that operates at the tool level, intercepting actions before they reach the game engine. When the curator tags an action as `[FATAL:keywords]` in the knowledge file, the protection layer:

1. Parses the FATAL tag to extract the action keywords and room context.
2. Before each action execution, checks whether the agent's intended action matches any FATAL entry.
3. If a match is found (action keywords appear as a substring of the intended action, and the current room matches or is unknown), the action is *blocked* — the game engine is never called, and the agent receives a blocking message.

Two important design constraints prevent over-blocking:

- **Scoring actions are never FATAL**: If an action appears in the scoring path (i.e., it sometimes increases score), it cannot be tagged as FATAL — the death is conditional, not guaranteed. The curator is instructed to describe such cases in the Unexplored section instead.
- **Navigation directions are room-conditional**: Generic movement commands (north, south, east, west, up, down) are almost never universally fatal — they depend on the specific room. When the agent's current room cannot be determined (e.g., the observation is an item description rather than a room name), navigation FATAL entries are *skipped* to avoid over-blocking, while non-navigation FATAL entries (e.g., casting a deadly spell) are *trusted* and blocked.

### 4.2 Loop Detection

Agents in text adventures frequently enter *behavioral loops* — repeatedly executing the same action in the same room without progress. Wiki-Evolve implements a loop detector that tracks action–location pairs over a sliding window of 10 steps:

1. Each action is recorded as an `(action, room_signature)` tuple.
2. If any single pair appears 5 or more times within the window, a loop warning is injected into the agent's feedback.
3. The warning includes *actionable suggestions*: the set of admissible commands not yet attempted in the current room (computed from the environment's admissible action list minus the tried set).

This design avoids the false-positive problem of action-only loop detection (where an agent moving north through multiple rooms would trigger a false alarm) by requiring both action and location to repeat.

---

## 5. Experimental Setup

### 5.1 Environment

We evaluate on six Jericho text adventure games spanning a range of difficulty and exploration complexity: Detective, Library, Zork1, Zork3, Balances, and Temple. Each game is played for $K=10$ episodes with a maximum of 110 steps per episode.

### 5.2 Models

The primary backbone is GLM-5.2 (accessed via BigModel coding API). Comparative experiments use DeepSeek-v4-Pro and Gemini-2.5-Flash. All experiments use the same framework configuration — only the LLM backbone differs.

### 5.3 Baselines

We compare against six baseline methods from the EvoTest benchmark, all using a Gemini backbone: EvoTest, EvoPrompt, Reflexion, GRPO, Memory, and Static (no learning).

### 5.4 Ablation Conditions

To isolate component contributions, we evaluate four configurations:

| Condition | Knowledge | Experience | World Model | Hard Protection |
|---|---|---|---|---|
| **Full** | ✓ | ✓ | ✓ | ✓ |
| w/ (Exp, WM), w/o (Know, HP) | ✗ | ✓ | ✓ | ✗ |
| w/ WM, w/o (Know, Exp, HP) | ✗ | ✗ | ✓ | ✗ |
| Naive ReAct | ✗ | ✗ | ✗ | ✗ |

---

## 6. Results

### 6.1 Main Results

Wiki-Evolve (GLM-5.2) achieves the highest normalized average score (58.3%) across all six games, outperforming all baselines:

| Method | Avg Normalized Score |
|---|---|
| **Wiki-Evolve (GLM-5.2)** | **58.3%** |
| Wiki-Evolve (DeepSeek-Pro) | 51.4% |
| EvoTest (GLM-5.2) | 35.8% |
| EvoTest (Gemini) | 32.4% |
| EvoPrompt (Gemini) | 24.5% |
| Reflexion (Gemini) | 21.5% |
| GRPO (Gemini) | 19.2% |
| Memory (Gemini) | 19.0% |
| Static (Gemini) | 11.9% |

### 6.2 Ablation Results

| Condition | TOTAL avg | Avg % | Δ vs Naive ReAct |
|---|---|---|---|
| **Full** | 432.8 | 58.3% | +280.1 (+183%) |
| w/ (Exp, WM), w/o (Know, HP) | 162.9 | 34.8% | +10.2 (+7%) |
| w/ WM, w/o (Know, Exp, HP) | 180.1 | 33.8% | +27.4 (+18%) |
| Naive ReAct | 152.7 | 33.6% | baseline |

**Key findings**:

- Semantic knowledge and hard protection together account for 96.4% of the total performance gain.
- The world model provides a modest but consistent improvement (+18% over Naive ReAct), with the largest gains on games requiring spatial navigation (Detective: +20.0 avg).
- Episodic experience retrieval, in the absence of semantic knowledge, shows limited benefit — the unstructured nature of raw trajectories yields low signal-to-noise ratio for action selection.

### 6.3 Hard Protection Counterfactual

A trajectory-level counterfactual analysis estimates the impact of FATAL interception: removing the hard protection layer would reduce Detective's average score from 297.0 to 165.0 (–44%), as 5 of 10 playthroughs would terminate at a known fatal junction. The total system average would drop from 58.3% to 40.5% normalized score.

Notably, the hard protection layer only covers one of three distinct death causes in Detective. The primary survival mechanism is *path guidance* — the semantic knowledge's scoring path steers the agent away from dangerous areas (e.g., the restaurant and the dazed man's room), preventing 9 of 10 deaths without any hard intervention.

### 6.4 Cross-Model Per-Game Analysis

We evaluate Wiki-Evolve with three LLM backbones on the same six games. Table 2 presents the per-game average and best scores for each model under the full configuration.

**Table 2. Per-game comparison across LLM backbones (Wiki-Evolve full, 10 episodes × 110 steps).**

| Game | Max Score | GLM-5.2 avg | GLM-5.2 best | DeepSeek-Pro avg | DeepSeek-Pro best | Gemini-Flash avg | Gemini-Flash best |
|---|---|---|---|---|---|---|---|
| Detective | 360 | **297.0** | 340 | 221.0 | **350** | 181.0 | 330 |
| Library | 30 | 29.1 | 30 | **29.8** | 30 | 19.3 | 30 |
| Zork1 | 350 | **61.6** | **99** | 35.5 | 59 | 31.1 | 49 |
| Zork3 | 7 | 3.6 | 5 | **3.8** | **5** | 2.5 | 5 |
| Balances | 51 | 19.5 | 20 | **20.5** | **30** | 14.5 | 15 |
| Temple | 35 | **22.0** | **25** | 15.0 | 15 | 9.7 | 15 |
| **TOTAL** | **833** | **432.8** | **519** | **325.6** | **489** | **258.1** | **444** |
| **Avg %** | | **58.3%** | | **51.4%** | | **33.8%** | |

**Key observations:**

- **GLM-5.2 ranks first overall** (432.8 avg, 58.3% normalized), outperforming DeepSeek-Pro by 33% despite Pro's stronger base reasoning. The advantage concentrates in Detective (+76.0 avg) and Temple (+7.0 avg), where precise instruction-following on long scoring paths matters most.
- **DeepSeek-Pro excels on smaller-score games** (Library, Zork3, Balances), where its stronger exploration capability discovers scoring actions that GLM-5.2 misses. Pro achieves the highest single-game best on Detective (350), Balances (30), and Zork3 (5).
- **Gemini-2.5-Flash** performs comparably to GLM-4.7 on the same framework (258.1 vs ~264 avg), confirming that the framework's benefit is model-agnostic.
- **GLM-5.2 vs GLM-4.7**: On the same six games, upgrading from GLM-4.7 to GLM-5.2 increases total average from 264.2 to 432.8 (+64%), with the largest gain on Detective (114.0 → 297.0). This demonstrates that the Wiki-Evolve framework amplifies backbone improvements — a stronger model derives disproportionately more benefit from structured knowledge.

Figure 3 illustrates the episode-by-episode score progression for Wiki-Evolve (GLM-5.2) against all baselines across the six games. Wiki-Evolve exhibits rapid early convergence (Detective: 130 → 330 within 4 episodes) and maintains a stable high-score plateau in later episodes, while baselines show slower or no convergence.

> **Figure 3.** Score per episode comparison. See `compare/comparison_glm52_only.png` for the full figure. Wiki-Evolve (GLM-5.2, red solid line) vs. seven baseline methods (colored dashed lines) across six Jericho games, 10 episodes. Baselines were evaluated with a Gemini backbone using the EvoTest benchmark framework; EvoTest (GLM-5.2) uses the same backbone as our method for fair comparison.

---

## 7. Discussion

### 7.1 Knowledge vs. Exploration

A central finding is that semantic knowledge — compressed, actionable rules distilled from prior experience — is the dominant contributor to performance. The world model and episodic experience provide supplementary value but cannot substitute for the guidance of a well-curated scoring path. This aligns with the intuition that in text adventures, the binding constraint is *knowing what to do next*, not *remembering where one has been*.

### 7.2 The Role of Hard Protection

The hard protection layer addresses a fundamental limitation of LLM-based agents: their unreliability in obeying negative constraints expressed in natural language. By intercepting fatal actions at the tool level, the system converts soft advisory warnings into hard guarantees. However, the counterfactual analysis reveals that path guidance (a soft mechanism) is ultimately more impactful — it prevents the agent from entering dangerous situations in the first place, rather than catching it at the last moment.

### 7.3 Knowledge–Experience Traceability

The bidirectional links between semantic knowledge and episodic evidence serve as a provenance mechanism. In practice, we observe that the play agent rarely follows these links (0 explicit followings across all experiments). However, the links provide significant value to the *curator* during the rewrite phase: by consulting linked experiences, the curator can verify whether a rule has been contradicted by newer evidence, enabling principled knowledge correction rather than blind accumulation.

### 7.4 Limitations

1. **Room disambiguation**: Games with multiple same-named rooms (e.g., multiple "Outside" locations) create ambiguity in both the knowledge representation and the FATAL matching logic. Addressing this requires richer room signatures incorporating distinguishing features.

2. **Conditional death modeling**: The current FATAL tag represents a binary (fatal/safe) classification. Deaths that depend on game state (e.g., "examine writing is safe on first reading but fatal after placing items on the table") cannot be captured, leading to either over-blocking (if tagged as FATAL) or under-protection (if omitted).

3. **Episode-scoped world model**: The current design resets the world model between episodes, preventing cross-episode spatial accumulation. A persistent graph could enable the agent to resume exploration from previously identified frontiers.

4. **Single-game knowledge**: Knowledge is scoped to a single game and does not transfer across games. Cross-game knowledge transfer (e.g., "text adventure games often hide keys in kitchens") remains unexplored.

---

## 8. Conclusion

Wiki-Evolve demonstrates that structured, persistent memory with explicit knowledge–experience traceability, spatial world modeling, and hard safety enforcement can substantially improve LLM agent performance in text adventure games — all without gradient updates. The framework's three-tier architecture, combined with iterative curation and safety mechanisms, achieves a 73% relative improvement over a memoryless baseline. Ablation analysis reveals that semantic knowledge distillation is the primary driver of performance, with the world model and hard protection providing complementary benefits. These findings suggest that the binding constraint for LLM agents in complex interactive environments is not model capacity per se, but the *organization and accessibility of accumulated experience*.

---

## References

1. Hausknecht, M. et al. (2020). Interactive Fiction Games: A Colossal Adventure. *AAAI*.
2. Yao, S. et al. (2023). ReAct: Synergizing Reasoning and Acting in Language Models. *ICLR*.
3. Shinn, N. et al. (2023). Reflexion: Language Agents with Verbal Reinforcement Learning. *NeurIPS*.
4. He, C. et al. (2025). EvoTest: Evolutionary Test-Time Learning for Self-Improving Agentic Systems.
5. Ammanabrolu, A. & Hausknecht, M. (2020). Graph-Constrained and Parsed Attention for Throne and the Room-Scale Text Adventure Games. *AAAI*.
