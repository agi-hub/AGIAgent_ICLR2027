# ScienceWorld Phase1 记忆资产创建说明

本文档说明 `apps/scienceworld/run_all_tasks.py` 在 `--baseline` 以外的模式（默认 two_stage）下，phase1 探索阶段如何产生、筛选并写入长期记忆资产文件。

---

## 1. 设计目标

Phase1 不是以完成任务为核心，而是以**积累可复用资产**为核心：

- 系统地探索环境（地点、对象、机制、状态变化、失败边界）
- 对高价值探索片段做结构化记录
- 用 LLM 蒸馏成世界知识和可复用技能
- 供 phase2 重新开局后检索使用

所有资产按 `env_name` 共享，不按 `variation_num` 切分。

---

## 2. 整体创建流程

```text
agent 执行 scienceworld_action
        │
        ▼
发现新状态 / 新对象 / 分数变化 / 失败边界
        │
        ▼
调用 trigger_curiosity(reason=...)
或在 response 中写 FLAG_CURIOSITY: yes + CURIOSITY_REASON: ...
        │
        ▼
ToolExecutor.trigger_curiosity() 记录好奇心信号
        │
        ▼
回合结束时 ToolExecutor 调用 BIAgentPipeline.process_curiosity_event()
        │
        ├──▶ SceneBuilder.build_scene()            构建 scene
        ├──▶ CuriosityScorer.score_scene()         好奇心评分
        │       │
        │       ├─ score >= theta_write  ──▶ SceneStore.append_scene()  写入 episodic_items.jsonl
        │       │
        │       └─ score >= theta_reflect ──▶ SceneReflector.reflect_scene()  LLM 反射
        │               │
        │               ▼
        │       WorldGraphManager.update_from_scene()  更新 world_graph.json
        │               │
        │               ▼
        │       SkillGraphManager.update_from_scene()  更新 skill_graph.json + skills/*.md
        │
        ▼
BIAgentPipeline._record_chunk_stat()  记录 chunk_stats.jsonl，用于饱和判断
```

---

## 3. 触发条件

Phase1 中每轮允许：

1. 一次 `scienceworld_action`
2. 随后最多一次 `trigger_curiosity`（不消耗环境步数）

触发时机由 prompt 规定，通常在以下情况：

- 发现新场景、新对象、新状态转移
- 遇到新的失败模式或可恢复路径
- 触发分数 / progress 变化

代码入口：

- `src/tool_executor.py` 第 2578 行：`trigger_curiosity()`
- `src/tool_executor.py` 第 3111 行附近：回合结束时调用 pipeline

---

## 4. 资产文件列表

所有资产统一存储在：

```text
data/default/general/biagent_memory/<AGIA_EXPERIMENT_NAMESPACE>/scienceworld/<env_name>/
```

例如：

```text
data/default/general/biagent_memory/scienceworld_valid_full/scienceworld/boil/
```

### 4.1 Scene 原始记录

| 文件 | 路径（相对 `<env_name>/`） | 说明 |
|------|---------------------------|------|
| `parsed/episodic_items.jsonl` | `parsed/episodic_items.jsonl` | 完整 scene 记录，每行一个 JSON |
| `parsed/segments.jsonl` | `parsed/segments.jsonl` | scene 轻量索引（scene_id / where / context / metrics） |

### 4.2 Reflection 结果

| 文件 | 路径 | 说明 |
|------|------|------|
| `reflections/<scene_id>.json` | `reflections/scene_xxxxxx.json` | LLM 对每个 scene 的蒸馏结果 |

### 4.3 图资产

| 文件 | 路径 | 说明 |
|------|------|------|
| `graphs/world_graph.json` | `graphs/world_graph.json` | 世界模型图：实体、地点节点、转移、规则 |
| `graphs/skill_graph.json` | `graphs/skill_graph.json` | 技能图：subgoals、skills、edges |
| `graphs/grounding_links.json` | `graphs/grounding_links.json` | grounding 链接 |
| `graphs/skills/<skill_id>.md` | `graphs/skills/*.md` | 人类可读的 skill 文档 |

### 4.4 统计与饱和信号

| 文件 | 路径 | 说明 |
|------|------|------|
| `parsed/chunk_stats.jsonl` | `parsed/chunk_stats.jsonl` | 每个 curiosity chunk 的统计，用于判断探索饱和 |

---

## 5. 各环节详细说明

### 5.1 构建 Scene

**代码**：`src/biagent/scene.py` → `SceneBuilder.build_scene()`

输入：

- `curiosity_info`：触发原因
- `all_tool_results`：最近几次 tool 调用结果
- `latest_response`：agent 上一步的回复
- `task_history`：任务历史

输出字段：

- `scene_id`：基于 env_name / round / reason 的哈希
- `where`：当前位置
- `entities`：从文本提取的实体
- `state_before` / `state_after`
- `events`：动作序列
- `outcome`：结果摘要
- `raw_context`：原始上下文

### 5.2 好奇心评分

**代码**：`src/biagent/curiosity.py` → `CuriosityScorer.score_scene()`

分数公式：

```text
score = alpha * novelty + beta * coverage + gamma * exception_bonus + delta * distillability
```

- `novelty`：与已有 scene 的 Jaccard 差异
- `coverage`：新实体 / 新地点 / 新关系的比例
- `exception_bonus`：失败、parser 错误、位置变化等异常奖励
- `distillability`：是否包含可蒸馏线索（score、progress、规则等）

关键阈值（可通过环境变量调整）：

```text
AGIA_BIAGENT_THETA_WRITE   = 0.45   # 达到才写 scene
AGIA_BIAGENT_THETA_REFLECT = 0.58   # 达到才调 LLM reflection
```

### 5.3 写入 Scene

**代码**：`src/biagent/scene.py` → `SceneStore.append_scene()`

```python
def append_scene(self, scene: Dict[str, Any]) -> None:
    _append_jsonl(self.env_paths.episodic_items_path, scene)
    segment = {
        "scene_id": scene.get("scene_id"),
        "trajectory_id": scene.get("trajectory_id"),
        "where": scene.get("where", ""),
        "context": scene.get("context", ""),
        "segment_reason": scene.get("segment_reason", ""),
        "status": scene.get("status", {}),
        "metrics": scene.get("metrics", {}),
    }
    _append_jsonl(self.env_paths.segments_path, segment)
```

### 5.4 LLM 反射

**代码**：`src/biagent/reflection.py` → `SceneReflector.reflect_scene()`

Prompt 文件：

```text
apps/scienceworld/prompts/scene_reflection_prompts.yaml
```

输出 JSON 包含：

- `summary`：scene 价值摘要
- `causal_summary`：因果描述
- `world_facts`：世界规则（条件 → 结论）
- `skill_candidate`：可复用局部策略
- `open_questions`：未解决问题

反射结果写进 `reflections/<scene_id>.json`，同时合并到 scene 的 `reflection` 字段。

### 5.5 更新世界模型图

**代码**：`src/biagent/world_graph.py` → `WorldGraphManager.update_from_scene()`

从 scene 提取并写入 `world_graph.json`：

- `entities`：去噪后的实体名
- `state_nodes`：地点节点
- `transitions`：`from_state | action | to_state`
- `rules`：world_facts 和 ordering_constraints

### 5.6 更新技能图

**代码**：`src/biagent/skill_graph.py` → `SkillGraphManager.update_from_scene()`

从 scene 的 `reflection.skill_candidate` 提取：

- title / activation / postcondition
- core_steps（具体动作字符串）
- ordering_constraints
- related world facts / entities / transitions

写入：

- `graphs/skill_graph.json`
- `graphs/skills/<skill_id>.md`

skill markdown 包含：Activation / Postcondition / Preconditions / Ordering Constraints / Execution / Summary 等章节。

---

## 6. 流程调度中枢

**代码**：`src/biagent/pipeline.py` → `BIAgentPipeline.process_curiosity_event()`

核心逻辑：

```python
scene = scene_builder.build_scene(...)
score_result = curiosity.score_scene(scene, existing_scenes, world_graph, skill_graph)

if score_result.get("should_write"):
    scene_store.append_scene(scene)
    if score_result.get("should_reflect"):
        reflection_result = reflector.reflect_scene(scene, ...)
        world_model_result = world_manager.update_from_scene(scene)
        graph_skill_result = skill_manager.update_from_scene(scene, world_model_result)
```

同时调用 `_record_chunk_stat()` 写入 `chunk_stats.jsonl`，用于判断探索是否饱和。

---

## 7. 探索饱和停止

`BIAgentPipeline._record_chunk_stat()` 跟踪最近多个 chunk 的好奇心得分。如果连续多个 scene 得分都低于阈值，会返回 `exploration_stop` 信号，agent 可能提前结束 phase1。

相关代码：

- `src/biagent/pipeline.py` → `_record_chunk_stat()`
- `src/biagent/curiosity.py` → 评分逻辑

可调环境变量：

```text
AGIA_BIAGENT_STOP_WINDOW              # 饱和判断窗口大小，默认 7
AGIA_BIAGENT_IDLE_ROUND_WINDOW        # 空闲轮窗口，默认 12
AGIA_BIAGENT_STOP_EPSILON             # 停止阈值，默认 1.75
AGIA_BIAGENT_STOP_CURIOSITY_EPSILON   # 好奇心停止阈值，默认 0.18
```

---

## 8. 与 Phase2 / Baseline 的区别

| 特性 | Phase1 | Phase2 | Baseline |
|------|--------|--------|----------|
| 目标 | 探索并写资产 | 用资产求解 | 无记忆直接求解 |
| `AGIA_EXPERIMENT_PHASE` | `phase1_explore` | `phase2_solve` | `phase_baseline` |
| 允许检索 | ❌ | ✅（受预算限制） | ❌ |
| 允许写资产 | ✅ | ✅（需 online learning） | ❌ |
| `trigger_curiosity` | ✅ | ✅（可记录但不写） | ✅（不写入） |

---

## 9. 相关代码文件速查

| 功能 | 文件 |
|------|------|
| 触发好奇心信号 | `src/tool_executor.py` |
| 调度整个 pipeline | `src/biagent/pipeline.py` |
| 构建 scene | `src/biagent/scene.py` |
| 好奇心评分 | `src/biagent/curiosity.py` |
| LLM 反射 | `src/biagent/reflection.py` |
| 世界模型图 | `src/biagent/world_graph.py` |
| 技能图 | `src/biagent/skill_graph.py` |
| 存储路径解析 | `src/biagent/paths.py` |
| Phase1/2/baseline 入口 | `apps/scienceworld/run_all_tasks.py` |
| Phase1 反射 prompt | `apps/scienceworld/prompts/scene_reflection_prompts.yaml` |
