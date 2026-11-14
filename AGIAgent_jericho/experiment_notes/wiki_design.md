# Wiki 记忆系统设计文档

> 本文档描述 `~/AGIAgent_wiki` 项目的记忆系统架构。该系统完全替换了原有的 biagent/curiosity/skill_evolve 记忆子系统。

---

## 1. 设计动机

原有系统存在以下问题：

- **数据散落**：三套平行子系统（biagent_memory、graph_experience、world_model_graph），数据分散在大量 JSON/JSONL 文件中，不直观
- **提取质量差**：world graph 依赖正则提取，location/entity 提取噪声大，entity 提取几乎无效
- **好奇心触发率低**：phase1 中模型 152 步 action 只触发 0 次 trigger_curiosity，world graph 积积累率 ~3%
- **激励错位**：模型解题时没有动机调用记忆工具（代价是模型的，收益是 phase2 的）
- **检索效果差**：grep 精确匹配无法处理同义词/语义近似，85% 查询返回 0 匹配

新系统用 wiki 风格的 Markdown 知识库 + embedding 检索 + post-hoc 总结（phase_m）解决上述问题。

---

## 2. 总体架构

### 2.1 三阶段流水线

```
phase1_explore          phase_m              phase2_solve
(求解+探索)              (记忆总结)            (wiki辅助求解)
     │                      │                      │
     │ 200轮,无记忆工具      │ 15轮,读写wiki         │ 100轮,读wiki
     │ 轨迹自动存盘          │ 读trajectory.jsonl    │ wiki_memory_read
     ▼                      ▼                      ▼
trajectory.jsonl ──→ phase_m更新wiki ──→ phase2检索wiki
```

- **phase1**：大模型只做任务求解，不调用任何记忆工具。每轮的工具调用及返回结果自动记录到 `trajectory.jsonl`
- **phase_m**（memory phase）：phase1 完成后自动触发。大模型读取 trajectory.jsonl，分析新鲜信息，用 terminal 工具写入 wiki Markdown 文件
- **phase2**：大模型通过 `wiki_memory_read`（embedding 检索）读取 wiki 辅助求解

### 2.2 各阶段工具可用性

| 工具 | phase1 | phase_m | phase2 |
|---|---|---|---|
| `scienceworld_action` | ✅ | ✅ | ✅ |
| `wiki_memory_read` | ❌ | ✅ | ✅ |
| `run_terminal_cmd` | ✅ | ✅ | ✅ |

- phase1 不提供 `wiki_memory_read`（纯求解，不查记忆）
- phase_m 需要 `run_terminal_cmd` 来读写 wiki 文件，需要 `wiki_memory_read` 来查重

### 2.3 任务调度

- 每个 task 内部串行：phase1 → phase_m → phase2
- task 之间并行：`--parallel-tasks N` 控制并行度
- 不同 task 的 phase_m 写同一个全局共享 wiki 目录

---

## 3. Wiki 存储结构

### 3.1 目录布局

```
data/default/general/wiki/<experiment_name>/
├── _index.md                    # 总索引（可选）
├── knowledge/                   # 知识技能（skill）
│   ├── boil_tactics.md
│   ├── freeze_mercury_recipe.md
│   └── ...
├── experiences/                 # 曾经经历（按关键事件/教训）
│   ├── 2026-06-20/
│   │   ├── boil-var014.md
│   │   └── freeze-var017.md
│   └── ...
├── world_model/                 # 世界模型（导航+物体）
│   ├── locations/
│   │   ├── kitchen.md
│   │   ├── hallway.md
│   │   └── ...
│   └── objects/
│       ├── stove.md
│       ├── freezer.md
│       └── ...
└── .wiki_index.npz              # embedding 索引缓存（自动管理）
```

**作用域**：全局共享。所有 ScienceWorld 任务（boil/freeze/melt/...）共用一个 wiki。通过页面 front-matter 中的 `applies_to` 字段区分适用范围。

### 3.2 页面格式

Markdown + 可选 YAML front-matter：

```markdown
---
applies_to: [all]            # [all] 表示通用知识，或 [boil, freeze] 表示特定任务
sources: [boil-var014]        # 来源经历
---

# Kitchen

厨房是一个有加热和制冷设备的房间。

## 物体
- stove - 加热设备，可以激活
- oven - 烤箱，需要先开门再放入物体
- freezer - 冷冻设备

## 连通
- hallway - 通过门连接（需要先 open door）
```

### 3.3 写入规则

- **knowledge**：可复用的战术、配方、ordering constraint（如"focus on substance before heating"）、失败模式、parser quirk
- **experiences**：每次任务的关键教训（非完整流水账），按日期组织
- **world_model/locations**：房间页面，含连通性、出口、内含物体
- **world_model/objects**：物体页面，含功能、spawn 位置、交互历史

### 3.4 冲突处理

**核心原则：wiki 信息只增不删，冲突时追加而非覆盖。**

| 场景 | 处理方式 |
|---|---|
| 房间连通性矛盾 | 两边都记录，注明来源经历和时间 |
| 物体功能描述不同 | 保留多种描述，标注"存在分歧" |
| 物体位置不同 | 记录为"物体可能出现在 A 或 B"，注明各自来源 |

---

## 4. 核心组件

### 4.1 trajectory.jsonl（轨迹存盘）

**位置**：`<output_dir>/logs/trajectory.jsonl`

**写入时机**：`tool_executor.py` 主循环中，每轮工具执行后由 `_append_trajectory_record` 方法追加写入。

**记录的工具**：`scienceworld_action`、`wiki_memory_read`、`run_terminal_cmd`

**scienceworld_action 记录的字段**：

```json
{
  "round": 1,
  "tool": "scienceworld_action",
  "params": {"action": "look around", "env_name": "boil"},
  "action": "look around",
  "observation": "This room is called the kitchen...",
  "task_description": "Your task is to boil water...",
  "current_score": 0,
  "best_score": 0,
  "progress": 0,
  "done": false,
  "won": false,
  "steps_taken": 1
}
```

**设计原因**：原有的 manager.log 只记录 LLM 输出和工具调用，不记录工具返回结果（observation/score/feedback）。phase_m 需要完整的 action→observation→score 轨迹才能提炼知识。

### 4.2 wiki_memory_read（embedding 检索工具）

**实现文件**：`src/wiki_memory.py`

**检索方式**：embedding 语义相似度（非 grep 精确匹配）

**模型**：`sentence-transformers/all-MiniLM-L6-v2`（384 维，轻量快速）

**工作流程**：
1. 收集 wiki 目录下所有 .md 文件
2. 检查 `.wiki_index.npz` 缓存是否有效（基于文件 mtime 哈希）
3. 缓存过期则重建：对每个页面的 title + content[:500] 做 embedding
4. 对查询做 embedding，计算 cosine 相似度
5. 返回 top-k（默认 10）个相似度 > 0.15 的页面，含内容片段

**为什么用 embedding 而非 grep**：
- grep 命中率 15%（85% 查询返回 0 匹配），embedding 几乎 100% 命中
- `how to freeze mercury` 能匹配到 `freeze_mercury_ultra_low_freezer_method.md`（语义相近）
- `boil caesium` 能匹配到 `boil_caesium_oven_method.md`（词形变化不影响）
- 实测 Phase2 精度从 0.62（grep）提升到 0.92（embedding）

**参数**：
- `query`（必填）：自然语言搜索字符串
- `section`（可选）：knowledge / experiences / world_model / locations / objects / all
- `max_results`（可选）：默认 10

### 4.3 phase_m（记忆总结阶段）

**触发**：`run_all_tasks.py` 中 `_run_task_two_stage` 函数，在 phase1 完成后、phase2 之前自动触发。

**环境变量**：`AGIA_WIKI_ROOT` 设置为 wiki 根目录，`AGIA_EXPERIMENT_PHASE` 设为 `phase_m`。

**输入**（通过 requirement 字符串注入）：
- 任务名和 variation
- wiki 根目录路径
- trajectory.jsonl 路径

**智能体工作流程**：
1. 用 `run_terminal_cmd`（python3 -c 或 cat/head/tail）分段读取 trajectory.jsonl
2. 分析轨迹，判断哪些是新信息（好奇心判断由 LLM 自行完成，无外部计算）
3. 用 `wiki_memory_read` 检查信息是否已存在
4. 用 `run_terminal_cmd`（python3 -c "open(...).write(...)"）写入/更新 wiki Markdown 文件

**提示词文件**：`apps/scienceworld/prompts/phase_m_prompt.txt`

---

## 5. 代码结构

### 5.1 核心文件

| 文件 | 职责 |
|---|---|
| `src/wiki_memory.py` | `WikiMemoryReader` 类：embedding 检索 + 索引缓存 |
| `src/tool_executor.py` | 工具注册（scienceworld_action + wiki_memory_read + run_terminal_cmd）+ trajectory.jsonl 记录（`_append_trajectory_record` 方法） |
| `src/tools/scienceworld_tools.py` | ScienceWorldEnv 封装 |
| `apps/scienceworld/run_all_tasks.py` | Runner：phase1→phase_m→phase2 调度 + requirement 生成 |
| `apps/scienceworld/prompts/phase_m_prompt.txt` | phase_m 系统提示词 |
| `apps/scienceworld/prompts/system_prompt.txt` | phase1/phase2 系统提示词 |
| `apps/scienceworld/prompts/rules_prompt.txt` | 规则提示词 |
| `apps/scienceworld/prompts/tool_prompt.json` | 工具 schema 定义（3 个工具） |

### 5.2 tool_executor.py 中的关键方法

| 方法 | 作用 |
|---|---|
| `_append_trajectory_record(round_num, all_tool_results)` | 每轮工具执行后写 trajectory.jsonl |
| 工具注册（`__init__` 中） | 注册 scienceworld_action、wiki_memory_read、run_terminal_cmd |

### 5.3 run_all_tasks.py 中的关键函数

| 函数 | 作用 |
|---|---|
| `_explore_requirement(env_name, variation, ...)` | 生成 phase1 的 requirement（纯求解，无记忆工具） |
| `_phase_m_requirement(env_name, variation, wiki_root, trajectory_log_path)` | 生成 phase_m 的 requirement（读轨迹+写wiki） |
| `_solve_requirement(env_name, variation, ...)` | 生成 phase2 的 requirement（wiki 辅助求解） |
| `_build_run_item(...)` | 构建 run item，包含 explore_phase + phase_m_phase + solve_phase |
| `_run_task_two_stage(...)` | 串行调度 phase1 → phase_m → phase2 |

### 5.4 CLI 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--explore-loops` | 200 | phase1 最大轮数 |
| `--phase-m-loops` | 15 | phase_m 最大轮数（0=禁用） |
| `--solve-loops` | 100 | phase2 最大轮数 |
| `--parallel-tasks` | 2 | 并行任务数 |
| `--fixed-dataset-split` | total | 数据集切片（total/test/valid） |
| `--experiment-name` | — | 实验名，影响输出和 wiki 目录 |

### 5.5 环境变量

| 变量 | 作用 |
|---|---|
| `AGIA_EXPERIMENT_NAMESPACE` | 实验 namespace，用于 wiki 目录和日志路径 |
| `AGIA_EXPERIMENT_PHASE` | 当前 phase 名（phase1_explore / phase_m / phase2_solve） |
| `AGIA_WIKI_ROOT` | wiki 根目录（phase_m 和 phase2 中由 run_all_tasks.py 设置） |
| `AGIA_WIKI_EMBEDDING_MODEL` | embedding 模型名（默认 all-MiniLM-L6-v2） |

---

## 6. 运行方式

### 全量运行

```bash
python apps/scienceworld/run_all_tasks.py \
  --selection-mode fixed_total \
  --fixed-dataset-split total \
  --explore-loops 200 \
  --phase-m-loops 15 \
  --solve-loops 100 \
  --parallel-tasks 2 \
  --experiment-name scienceworld_wiki_full
```

### 禁用 phase_m

```bash
python apps/scienceworld/run_all_tasks.py --phase-m-loops 0 ...
```

### 仅跑 phase1

```bash
python apps/scienceworld/run_all_tasks.py --phase1-only ...
```

### 测试

```bash
python -m unittest tests.test_scienceworld_entry
```

---

## 7. 已删除的旧系统

| 删除内容 | 规模 | 说明 |
|---|---|---|
| `src/biagent/` | ~2,100 行 | curiosity 流水线、scene builder、world/skill graph managers、reflection、retrieval |
| `src/skill_evolve/` | ~3,800 行 | skill tools、graph skill、world model tools、curiosity_flag |
| `tool_executor.py` 中记忆代码 | ~1,606 行 | trigger_curiosity、所有 query/write_skill 工具、好奇心提取、asset lock、phase 门控 |
| 旧 prompt 文件 | 4 个 | memory_tools.json、graph_skill_prompts.yaml、world_model_prompts.yaml、scene_reflection_prompts.yaml |
| 旧数据目录 | 6 个 | biagent_memory/、graph_experience/、world_model_graph/、experience/、_curiosity_runtime/、_asset_update_locks/ |
| WUE 评估器 | 3 个文件 | world_understanding_evaluator.py、run_wue_on_batch.py、wue_usage.md |

**总计删除约 7,500 行代码。**
