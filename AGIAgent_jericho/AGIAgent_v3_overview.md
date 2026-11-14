# AGIAgent_v3 简要说明

本文简要记录 `AGIAgent_v3` 相对 `AGIAgent_v2` 在 TextQuests 实验中的主要功能变化、关键代码位置、资产路径、常用参数和运行命令。

## 主要变化

`AGIAgent_v3` 的核心变化是加入了更明确的 **BIAgent 探索-资产-检索流程**，使 TextQuests 从单阶段执行变为两阶段执行：

- **两阶段实验流程**：`phase1_explore` 负责探索和资产沉淀，`phase2_solve` 重新开始任务并检索 phase1 资产辅助求解。
- **显式 curiosity 触发**：Phase1 通过 `trigger_curiosity` 主动记录新场景、新物体、新状态转移、失败边界、恢复路径和 score/progress 触发点。
- **scene / reflection 资产**：高价值探索片段会被整理成 scene，并通过 LLM 反思蒸馏为可复用世界知识和技能候选。
- **世界模型资产**：新增 `world_graph.json`，记录实体、状态节点、规则和状态转移。
- **技能模型资产**：新增 `skill_graph.json` 和 `skills/*.md`，记录局部可执行技能、触发条件、核心步骤、后置状态和失败信号。
- **world-skill 轻量联动**：新增 `grounding_links.json`，把 skill 与相关 world rule、entity、transition 关联起来；`query_world_model` 可以返回 world-grounded `linked_skills`。
- **observation-grounded retrieval**：Phase2 不再只按任务名粗检索，而是先 `look` 获取当前 observation，再用 `env_name + current_observation + local goal` 查询 skill、graph skill 和 world model。
- **低置信度 fallback**：检索命中弱时，会补充返回 reflection/scene 证据作为参考。
- **技能质量过滤**：只有包含具体 TextQuests 命令步骤的技能候选才会写入 skill graph，减少地点描述或抽象事实污染技能库。
- **探索饱和早停**：根据最近窗口内 world/skill 资产增益、curiosity 和重复区域/失败边界判断 Phase1 是否收敛。
- **parser / anti-loop / restore 保护**：Phase2 增加 parser recovery、重复动作拦截、非法 restore checkpoint 拦截和 progress preservation 约束。
- **best_progress 评估保护**：记录历史最高 `best_progress`，benchmark summary 和 official progress alignment 优先使用它，避免最终错误 restore 污染评估。
- **prompt 统一整理**：TextQuests 运行、检索、反思、world model、graph skill 等 prompt 已统一为更清晰的阶段化和规则化表达。

## 关键代码文件

- `apps/textquests/run_all_tasks.py`：TextQuests 两阶段批量实验入口，负责任务选择、并行、manifest、summary、Phase1/Phase2 prompt。
- `src/biagent/pipeline.py`：BIAgent 主流程，处理 `trigger_curiosity`，写入 scene/world/skill 资产，并判断探索饱和。
- `src/biagent/curiosity.py`：curiosity 评分、写入阈值、反思阈值和 cold-start/model-driven scoring。
- `src/biagent/scene.py`：把 observation、工具结果和历史上下文整理成 scene/segment/episodic item。
- `src/biagent/reflection.py`：对高价值 scene 做 LLM 反思。
- `src/biagent/world_graph.py`：维护世界模型，并输出 rule/entity/transition 关联。
- `src/biagent/skill_graph.py`：维护技能模型，并把 skill 与世界模型关联写入 `grounding_links.json`。
- `src/biagent/retrieval.py`：Phase2 检索入口，包含 skill、graph skill、world model、fallback evidence 和 `linked_skills`。
- `src/tools/textquests_tools.py`：TextQuests 单步交互工具，包含 checkpoint/restore、parser feedback、anti-loop、best_progress。
- `src/tool_executor.py`：连接 agent 工具调用与 BIAgent pipeline，控制 phase2 是否继续在线写资产。

## 资产保存路径

BIAgent 资产按实验名、应用名和环境名隔离：

```text
data/default/general/biagent_memory/<experiment_name>/<app_name>/<env_name>/
```

以 TextQuests 的 `ballyhoo` 为例：

```text
data/default/general/biagent_memory/<experiment_name>/textquests/ballyhoo/
```

主要文件：

- `parsed/episodic_items.jsonl`：原始经历条目。
- `parsed/segments.jsonl`：结构化场景片段。
- `parsed/chunk_stats.jsonl`：curiosity、资产增益和早停相关统计。
- `reflections/reflection_<scene_id>.json`：高价值 scene 的反思结果。
- `graphs/world_graph.json`：实体、状态节点、规则、状态转移。
- `graphs/skill_graph.json`：subgoal、skill、触发条件、后置状态和 world 关联字段。
- `graphs/skills/*.md`：单个技能说明。
- `graphs/grounding_links.json`：world-skill 关联，用于从 world model 命中反查 `linked_skills`。

实验结果和日志：

```text
data/benchmark_results/<experiment_name>/
data/default/general/experience/<experiment_name>/logs/
```

## 常用可调参数

这些参数均通过环境变量读取；未设置时使用代码默认值。

- `AGIA_BIAGENT_THETA_WRITE`：scene 写入阈值，默认 `0.45`。
- `AGIA_BIAGENT_THETA_REFLECT`：触发反思阈值，默认 `0.58`。
- `AGIA_BIAGENT_ALPHA/BETA/GAMMA/DELTA`：curiosity 中 novelty、coverage、exception、distillability 权重，默认 `0.30/0.30/0.15/0.25`。
- `AGIA_BIAGENT_STOP_WINDOW`：探索饱和判断窗口，默认 `7`。
- `AGIA_BIAGENT_STOP_EPSILON`：平均资产增益低于该值时认为趋于饱和，默认 `1.75`。
- `AGIA_BIAGENT_STOP_CURIOSITY_EPSILON`：低 curiosity 辅助早停阈值，默认 `0.18`。
- `AGIA_BIAGENT_REPEAT_REGION_THRESHOLD`：重复区域 guardrail，默认 `4`。
- `AGIA_BIAGENT_REPEAT_FAILURE_THRESHOLD`：重复失败边界 guardrail，默认 `3`。
- `AGIA_BIAGENT_ASSET_ALPHA/ASSET_BETA`：资产增益中 world 与 skill 权重，默认 `0.65/0.35`。
- `AGIA_BIAGENT_PHASE2_ONLINE_LEARNING`：是否允许 Phase2 继续写长期资产，默认关闭。

## 运行示例

在 `AGIAgent_v3` 根目录运行单任务实验：

```bash
python apps/textquests/run_all_tasks.py \
  --task-list "[1]" \
  --explore-loops 1000 \
  --solve-loops 500 \
  --experiment-name textquests_v3_task1_test
```

当前代码默认参数已与 `textquests_v3_all25_p4_conservative_fixes_F_like` 实验一致。需要临时覆盖时可显式传环境变量：

```bash
AGIA_BIAGENT_STOP_EPSILON=1.55 \
AGIA_BIAGENT_STOP_WINDOW=8 \
AGIA_BIAGENT_THETA_REFLECT=0.57 \
python apps/textquests/run_all_tasks.py \
  --task-list "[1]" \
  --explore-loops 1000 \
  --solve-loops 500 \
  --experiment-name textquests_v3_task1_param_test
```

## 查看资产质量

建议重点看：

- `parsed/chunk_stats.jsonl`：后期 `delta_a_cur` 是否接近 0，是否出现大量重复区域。
- `graphs/world_graph.json`：实体、状态、规则、转移是否清晰且不过度重复。
- `graphs/skill_graph.json` 和 `graphs/skills/*.md`：技能是否可执行，是否覆盖关键 puzzle、失败边界和恢复路径。
- `graphs/grounding_links.json`：skill 是否关联到具体 world rule/entity/transition。
- Phase2 日志：`query_world_model` 的 `linked_skills` 是否与当前 observation 相关且可验证。

