# BIAgent Phase1 认知抽取改进方案

## 背景

当前 BIAgent 从 ScienceWorld 轨迹中抽取的世界模型（`world_graph.json`）和技能模型（`skill_graph.json`）停留在原子操作层，难以支撑 Phase2 的任务求解与跨任务迁移。本方案合并了两个独立诊断的共识，提出系统性的改进路径。

---

## 一、核心问题诊断

### 问题 1：世界模型碎片化，无层次结构

**表现：**

- `world_graph.json` 中规则全部是一阶的 If X then Y，且严重重复。
- 同一地点被描述多次（如 kitchen 在 freeze 中被描述 4 次以上），措辞略有不同但本质相同。
- `state_nodes` 把 `"You move to the kitchen."` 和 `"kitchen"` 当作两个独立节点。
- 没有实体属性（如 stove 是热源、freezer 是冷源），没有实体关系（如 kitchen 包含 stove）。
- 没有任务目标模型 —— boil/freeze/melt 任务到底需要哪些步骤、哪些物质是目标物质、哪些设备是关键设备。

**根因：**

- `SceneBuilder.build_scene()` 中 `state_before/after` 只保存 `location` 字符串，没有结构化世界状态。
- `WorldGraphManager.update_from_scene()` 用原始观察文本作为地点名，transition 只记录单步命令，rule 用精确字符串匹配去重。

---

### 问题 2：技能模型是单步原语，非组合策略

**表现：**

- `skill_graph.json` 中绝大多数技能是 `"go to X"`、`"open Y"` 这种单步操作。
- 例如打开 freezer 的技能只有一步 `open freezer`，不是“获取目标物质”的完整策略。
- 缺失的关键技能：
  - 从任意房间导航到厨房（多步路径规划）
  - 获取目标物质（定位 → 导航 → 打开容器 → 取出）
  - 完成 boil/freeze 完整任务链（找到物质 → 带到热源/冷源 → 放入容器 → 操作）

**根因：**

- `scene_reflection_prompts.yaml` 要求 `core_steps` 保留原始命令字符串，禁止抽象化。
- `SkillGraphManager` 的 merge key 基于具体 title + activation + postcondition，默认 fallback 到地点字符串。
- `curiosity.py` 评分奖励新地点/新对象，不奖励跨 scene 的技能组合或策略链发现。

---

### 问题 3：Reflection Prompt 只引导提取局部事实

**表现：**

- 每个 scene 最多只能输出 3 条 `world_facts`。
- 不引导推理任务目标结构、物体 affordance、空间结构、因果链。
- 不将当前发现与已有知识做归纳泛化。
- 例如 agent 已经发现 stove 在 kitchen、lead 在 workshop，但 reflection 从未产出“厨房是热源所在地，workshop 是物质存放地”这种功能性认知。

**根因：**

- Prompt 的口号（"Extract reusable world knowledge"）与字段规则（"concrete location/object/command"）之间存在目标冲突。
- 没有要求 LLM 输出 `task_model`、`object_affordances`、`spatial_structure` 等高层字段。

---

### 问题 4：没有跨 Scene 的知识归纳/综合步骤

**表现：**

- Pipeline 是逐 scene 增量追加，从不做全局综合。
- 4 条关于 kitchen 的规则没有被合并为 1 条结构化描述。
- 不同 variation 的共同模式没有被泛化（如 boil/freeze/melt 都涉及物质状态变化）。
- 原子技能没有被链接为策略链（如 `open door` → `go to kitchen` → `open freezer` → `take substance`）。
- `open_questions` 只记录不驱动后续探索，例如“Does placing a substance inside the activated blast furnace cause it to boil?”从未被验证。

**根因：**

- `BIAgentPipeline.process_curiosity_event()` 只处理单个 scene，没有 phase1 结束后的 consolidation phase。
- `retrieval.py` 也没有优先检索高层综合资产。

---

### 问题 5：Curiosity 评分鼓励探索新地点，而非验证关键因果假设

**表现：**

- Agent 跨多个 variation 运行时，最高得分停滞在较低水平。
- Agent 会 activate blast furnace / stove，但很少把物质放入容器再加热/冷冻。
- 大量探索预算花在“走来走去”上，而不是验证 `open_questions` 中的关键假设。

**根因：**

- `CuriosityScorer.score_scene()` 的 `novelty/coverage` 奖励新词、新地点、新 transition。
- `exception_bonus` 奖励换房间、失败词、输赢标记。
- 没有任何一项奖励：发现抽象规则、解释异常原因、验证 open question、形成可迁移 skill。

---

### 问题 6：Phase1 探索策略被 Prompt 锁定在“广度覆盖”，回避深度因果验证

**表现（基于 59 个 manager.out 轨迹的量化分析）：**

- **动作高度集中在低层次移动/观察/开门**：
  - `move`: 37.9%–44.6%
  - `observe`: 22.4%–25.6%
  - `door_container`: 23.2%–26.0%
  - 三者合计占 **85.5%–91.2%**
- **真正改变物体状态的操作极少**：
  - `take`: 0.5%–1.9%
  - `put`: 0.4%–2.1%
  - `activate`: 1.3%–2.8%
  - `focus`: 0.1%–0.8%
  - 深度交互合计仅 **4.1%–8.5%**
- **约 1/3 的轨迹完全没有深度交互**：19/58（32.8%）的轨迹只有 move/observe/open。
- **最频繁动作是 `go to hallway`**，出现 717 次，占总动作 14.8%。Agent 不断在房间之间往返，却很少把物质带到热源/冷源。
- **即使做了 put+activate，也经常是乱放的**：
  - `put soap in oven`
  - `put ice cream in oven`
  - `put rubber in ultra low temperature freezer` 后没有后续验证
- **得分分布显示探索没有收敛到解法**：
  - boil 平均 max_score 仅 7.5（满分通常 100）
  - freeze 平均 max_score 17.6
  - melt 平均 max_score 12.0（虽然有一个 var19 得了 100）

**根因：**

- Phase1 system prompt 明确写道：
  > "Prefer actions that test unvisited exits, inspect new objects, and resolve open frontiers before optimizing for score or final completion."
  > "Stay in exploration mode for the whole session: prefer covering new areas and diverse interactions over chasing final completion."
- 这条指令把 agent 锁定在“永远探索新地点、新对象”，使其把预算花在最容易获得 curiosity 奖励的低风险动作上（go to、open、look），而不是去尝试“把物质放进热源看是否沸腾”这种可能失败但更有信息量的实验。
- `CuriosityScorer` 没有惩罚重复房间转移，也没有奖励对 `open_questions` 的主动验证。

---

## 二、改进方案（分层实施）

### 层次 0：修正 Phase1 探索策略 —— 从“广度覆盖”转向“假设驱动的因果验证”

**目标：** 让 agent 在地图覆盖到一定程度后，主动验证关键因果假设，而不是无限换房间。

**具体改动：**

1. **改写 Phase1 system prompt**（`apps/scienceworld/prompts/` 下的 phase1 运行 prompt）：
   - 保留“前期进行 broad exploration 以建立空间地图”的指令。
   - 新增“当地图覆盖主要房间后，优先验证以下假设：
     - 目标物质与热源/冷源如何交互
     - 哪些容器可以承载目标物质
     - activate 设备后物质状态是否变化
     - 当前 `open_questions` 中哪些是最关键的未解问题"
   - 明确禁止无目的的来回移动："不要在没有明确探索目标的情况下重复访问已充分观察过的房间。"

2. **引入探索阶段切换机制**：
   - 阶段 A（前 20-30% 步数）：地图覆盖，发现房间、关键物体、目标物质。
   - 阶段 B（后 70-80% 步数）：假设验证，执行可能改变物质状态的操作序列。
   - 阶段切换可以基于：已访问不同房间数 ≥ 阈值，或 world_graph 节点数 ≥ 阈值。

3. **让 `open_questions` 驱动探索**：
   - 每次 reflection 产生的 `open_questions` 写入一个全局队列。
   - agent 的下一步动作优先选择能验证/排除队列中最高优先级问题的动作。
   - 例如：如果 open question 是“Does placing ice cream on stove cause it to boil?”，agent 应该执行 `take ice cream → go to kitchen → put ice cream on stove → activate stove`。

4. **增加“实验性动作”奖励**：
   - 对首次尝试 `take + put + activate` 这类完整操作链的动作序列给予额外 curiosity 奖励，即使失败也有信息价值。
   - 对无目的地重复访问同一区域施加惩罚。

**预期效果：** Agent 不再把 80% 的动作花在 go/look/open 上，而是会主动尝试“把物质放进热源/冷源”这类能推进任务理解的实验。

---

### 层次 2：改进 Reflection Prompt —— 引导高层认知提取

**目标：** 让每次 reflection 不仅记录局部事实，还产出功能性、抽象化、可迁移的认知。

**新增输出字段：**

```json
{
  "task_model": {
    "task_goal": "boil 任务要求将目标物质加热至沸腾状态",
    "goal_substance": ["tin", "lead", "gallium", "ice cream"],
    "required_apparatus": ["stove/blast furnace", "container (metal pot/ceramic cup)"],
    "critical_path": ["locate substance", "navigate to heat source", "place in container", "activate heat"]
  },
  "object_affordances": [
    {"object": "stove", "role": "heat_source", "actions": ["activate stove", "put X on stove"]},
    {"object": "freezer", "role": "cold_storage", "actions": ["open freezer", "take X from freezer"]}
  ],
  "spatial_structure": {
    "hub": "hallway",
    "spokes": ["kitchen", "bedroom", "workshop", "art studio", "greenhouse", "living room"],
    "key_paths": {"substance_location": "workshop", "heat_source": "kitchen/foundry"}
  },
  "skill_schema": {
    "title": "参数化技能模板",
    "activation": "agent 在 room X，需要获取 container Y 中的 substance Z",
    "parameters": {"X": "current room", "Y": "container", "Z": "substance"},
    "core_steps": ["open Y", "take Z from Y", "go to target room", "put Z on heat source"]
  }
}
```

**具体改动：**

1. 改写 `apps/scienceworld/prompts/scene_reflection_prompts.yaml`：
   - 移除 `world_facts` 最多 3 条的限制，或增加 `world_rules` 字段用于抽象规则。
   - 增加 `task_model`、`object_affordances`、`spatial_structure`、`skill_schema` 字段。
   - 明确要求区分 `concrete_trace`（当前观察）与 `abstract_schema`（泛化知识）。
2. 在 `src/biagent/reflection.py` 的 `normalize_reflection()` 中处理新字段，确保合法 JSON 结构。
3. 让 `WorldGraphManager` 和 `SkillGraphManager` 消费新字段中的抽象信息。

**预期效果：** Reflection 直接产出“厨房是热源所在地”、“workshop 存放目标物质”这类功能性认知，而不是只记录 `"go to kitchen"`。

---

### 层次 3：World Graph Consolidation —— 把碎片规则综合为结构化世界模型

**目标：** 在 phase1 结束或每 N 个 scene 后，用 LLM 把大量一阶规则综合成高层世界模型。

**新增方法：**

```python
# src/biagent/world_graph.py
class WorldGraphManager:
    def consolidate(self, llm_client) -> Dict[str, Any]:
        """
        用 LLM 将碎片化规则合并为结构化世界模型。
        输出写入 world_graph.json 的 consolidated_model 字段。
        """
        graph = self.load()
        # 1. 按地点/对象聚类相似规则
        # 2. 调用 LLM 综合为结构化描述
        # 3. 提取 spatial_layout / object_ontology / task_templates
        # 4. 写回 world_graph.json
```

**输出示例：**

```json
{
  "consolidated_model": {
    "spatial_layout": {
      "hub": "hallway",
      "rooms": {
        "kitchen": {"role": "heat_source_room", "key_objects": ["stove", "oven", "freezer", "lighter"], "access": "from hallway, open door first"},
        "workshop": {"role": "substance_storage", "key_objects": ["ultra_low_freezer", "electrical_components"], "access": "from hallway"},
        "foundry": {"role": "high_temperature_processing", "key_objects": ["blast_furnace"], "access": "from outside"}
      }
    },
    "object_ontology": {
      "heat_sources": ["stove", "oven", "blast_furnace", "lighter"],
      "containers": ["metal_pot", "ceramic_cup", "glass_jar", "jug"],
      "cold_storage": ["freezer", "ultra_low_freezer", "fridge"],
      "substances": {"lead": "workshop/jug", "gallium": "workshop/metal_pot", "ice_cream": "kitchen/freezer"}
    },
    "task_templates": {
      "boil": {
        "preconditions": ["locate target substance", "obtain suitable container", "reach heat source"],
        "critical_path": "substance → container → heat_source → activate",
        "scoring_triggers": ["activate blast furnace = +2 points"]
      },
      "freeze": {
        "preconditions": ["locate target substance", "reach cold storage"],
        "critical_path": "substance → cold_storage → activate/wait",
        "scoring_triggers": ["focus on ice cream = +38 progress"]
      }
    }
  }
}
```

**具体改动：**

1. 在 `src/biagent/world_graph.py` 中实现 `consolidate()`。
2. 准备 consolidation prompt，输入为当前所有 rules + state_nodes + transitions，输出为结构化模型。
3. 在 `src/biagent/pipeline.py` 的 phase1 结束阶段调用 `world_manager.consolidate(llm_client)`。

**预期效果：** 80 条碎片规则被综合为 rooms / object_ontology / task_templates 三层结构，消除重复，提升可检索性。

---

### 层次 4：Skill Graph Composition —— 把原子技能组合为任务级策略链

**目标：** 基于 world_graph 的空间结构和 skill 的动作模式，用 LLM 生成 macro_skills。

**新增方法：**

```python
# src/biagent/skill_graph.py
class SkillGraphManager:
    def compose_skills(self, llm_client, world_graph) -> Dict[str, Any]:
        """
        将原子技能组合为任务级策略链。
        输出写入 skill_graph.json 的 macro_skills 字段。
        """
        # 1. 按目标分组技能（导航类、获取类、操作类、转化类）
        # 2. 基于 world_graph 空间结构链接技能序列
        # 3. 调用 LLM 推理 macro_skills
```

**输出示例：**

```json
{
  "macro_skills": [
    {
      "macro_skill_id": "macro_boil_substance",
      "title": "Complete boil task sequence",
      "parameters": {"substance": "target substance", "container": "suitable container", "heat_source": "stove or blast furnace"},
      "phases": [
        {"phase": 1, "name": "locate_substance", "skills": ["go_to_workshop", "examine_container"], "expected_outcome": "found target substance"},
        {"phase": 2, "name": "obtain_substance", "skills": ["open_container", "take_substance"], "expected_outcome": "substance in inventory"},
        {"phase": 3, "name": "transport_to_heat", "skills": ["go_to_hallway", "go_to_kitchen"], "expected_outcome": "at kitchen with substance"},
        {"phase": 4, "name": "prepare_heating", "skills": ["put_substance_in_container", "activate_stove"], "expected_outcome": "substance heating"},
        {"phase": 5, "name": "complete", "skills": ["wait_or_focus"], "expected_outcome": "task score increase"}
      ],
      "unverified_steps": ["put substance in blast furnace"]
    }
  ]
}
```

**具体改动：**

1. 在 `src/biagent/skill_graph.py` 中实现 `compose_skills()`。
2. 对现有 skills 做预分类：navigation / acquisition / manipulation / transformation。
3. 过滤纯移动原子 skill，将其归入 navigation 子图，不作为独立 macro skill。
4. 调用 LLM 基于 world_graph 的 `spatial_layout` 和 `task_templates` 生成组合策略。

**预期效果：** 从 22 个原子技能中提炼出 `acquire_substance`、`setup_heating`、`complete_boil/freeze` 等可执行策略链。

---

### 层次 5：Pipeline Consolidation Phase —— 自动化综合与检索优先

**目标：** 在 phase1 探索结束后自动触发 consolidation，并让 Phase2 优先使用高层资产。

**流程：**

```text
Phase1 探索循环
    ↓
探索饱和 / 循环结束
    ↓
[新增] Consolidation Phase:
    1. world_manager.consolidate(llm_client) → 生成 consolidated_model
    2. skill_manager.compose_skills(llm_client, world_graph) → 生成 macro_skills
    3. 建立 task_decomposition 树
    4. 写回 graphs/ 目录
    ↓
Phase2 检索时优先使用 consolidated_model 和 macro_skills
```

**具体改动：**

1. 在 `src/biagent/pipeline.py` 中新增 `consolidate_knowledge(llm_client)` 方法。
2. 在 `run_all_tasks.py` 的 phase1 结束或饱和停止后调用该方法。
3. 在 `src/biagent/retrieval.py` 中：
   - 优先检索 `consolidated_model` 和 `macro_skills`。
   - 当高层检索命中不足时，再 fallback 到原始 rules / skills / scenes。
4. 可选：把 `open_questions` 中最关键、未验证的假设返回给 agent，驱动后续探索。

**预期效果：** Phase2 不再只看到“go to kitchen”这种单步提示，而是能看到“完成 boil 任务的完整策略链”。

---

### 层次 6：Curiosity 评分重构 —— 奖励抽象、因果与假设验证

**目标：** 让 agent 从“逛地图”转向“验证关键因果假设”。

**新增评分维度：**

| 维度 | 计算思路 |
|---|---|
| `abstraction_bonus` | reflection 输出参数化 rule / skill schema 时加分 |
| `causal_depth` | scene 包含失败→恢复、状态变化、score/progress 因果解释时加分 |
| `transferability` | 新 skill schema 与已有 skill 结构相似但参数不同时加分 |
| `anomaly_explanation` | 对 parser 错误或异常反馈给出结构化解释时加分 |
| `hypothesis_validation` | scene 验证了某个 `open_question` 中的假设时加分 |

**降低权重：**

- 降低纯地点发现、纯对象发现的 `coverage` 权重。
- 对重复访问同一区域的 scene 施加惩罚。

**具体改动：**

1. 在 `src/biagent/curiosity.py` 的 `score_scene()` 中新增上述维度。
2. 提供环境变量用于调整权重，如 `AGIA_BIAGENT_ABSTRACTION_WEIGHT`、`AGIA_BIAGENT_CAUSAL_WEIGHT`。

**预期效果：** Agent 更倾向于执行“把物质放进 blast furnace 看是否沸腾”这类能推进任务理解的探索，而不是继续换房间。

---

## 三、实施优先级

| 优先级 | 改进项 | 预期效果 | 改动量 | 关键文件 |
|---|---|---|---|---|
| P0 | 修正 Phase1 探索策略：从“广度覆盖”转向“假设驱动的因果验证” | agent 主动尝试 take/put/activate 完整链，减少无目的换房间 | 小 | `apps/scienceworld/prompts/` 下 phase1 运行 prompt，可选 `src/biagent/curiosity.py` |
| P0 | 改写 reflection prompt，增加 task_model / affordance / spatial_structure / skill_schema | reflection 直接产出高层认知 | 小 | `apps/scienceworld/prompts/scene_reflection_prompts.yaml`, `src/biagent/reflection.py` |
| P0 | 在 `reflection.py` 的 normalize 中处理新字段 | 新字段能正确流转到 graph | 小 | `src/biagent/reflection.py` |
| P0 | World Graph 地点/动作归一化 | 立即减少节点和 transition 重复 | 小 | `src/biagent/world_graph.py` |
| P1 | World Graph 增加 `consolidate()` 方法 + LLM 调用 | 碎片规则 → 结构化世界模型 | 中 | `src/biagent/world_graph.py` |
| P1 | Skill Graph 增加 `compose_skills()` 方法 | 原子动作 → 组合策略 | 中 | `src/biagent/skill_graph.py` |
| P1 | Skill Graph 过滤/归并纯移动 skill | 减少“go to X” 垃圾 skill | 小 | `src/biagent/skill_graph.py` |
| P2 | Pipeline 在 phase1 结束时调用 consolidation | 自动化综合 | 小 | `src/biagent/pipeline.py`, `apps/scienceworld/run_all_tasks.py` |
| P2 | Retrieval 优先检索 consolidated 资产 | Phase2 直接利用高层知识 | 小 | `src/biagent/retrieval.py` |
| P2 | Curiosity 评分增加抽象/因果/假设验证奖励 | 驱动关键因果探索 | 中 | `src/biagent/curiosity.py` |
| P3 | 跨任务 domain theory 层 | boil/freeze/melt 共享状态变化机制 | 大 | 新增 domain_theory 模块 |

---

## 四、推荐的最小可行改动（MVP）

如果希望快速验证效果，建议先做以下 5 件事：

1. **改 Phase1 探索策略 prompt**：明确禁止无目的来回移动，增加“当地图覆盖主要房间后，优先验证目标物质与热源/冷源的交互”的指令。
2. **改 reflection prompt**：让 reflection 输出 `task_model`、`object_affordances`、`spatial_structure`、`skill_schema`。
3. **改 scene 结构化**：在 `state_before/after` 中增加 rooms / objects / doors / inventory 的解析字段。
4. **改 world_graph 归一化**：把地点名归一化为 `room:kitchen`，动作归一化为 `move(target)`。
5. **改 skill_graph 过滤**：把只包含 `go`/`move`/`north`/`east` 的 skill 归入 navigation 子图，不单独生成独立 skill。

完成这 5 步后，重新跑一个 freeze/boil 任务，检查：

- 轨迹中 `move`/`observe`/`door_container` 占比是否从 90% 降到 70% 以下。
- `take`/`put`/`activate` 等深度交互是否明显增加。
- `world_graph.json` 中是否出现 `rooms` / `object_ontology` 等结构化字段。
- `skill_graph.json` 中是否减少“go to X”技能，增加带参数的技能模板。
- reflection 是否开始产出“厨房是热源所在地”这类功能性认知。

---

## 五、验证指标

改进后建议用以下指标评估资产质量：

| 指标 | 当前问题 | 期望状态 |
|---|---|---|
| 动作类型分布 | move+observe+door_container 占 90.8% | 降到 < 70%，take/put/activate/focus 明显增加 |
| 无深度交互轨迹比例 | 32.8% 的轨迹只有 move/look/open | < 10% |
| 独立地点节点数 | 同一 kitchen 出现多次 | 每个物理房间只出现一次 |
| 独立技能数 | 22 个，大多单步 | 5-10 个 macro skills + 少量原子技能 |
| 技能平均步数 | 1.0 | > 2.0 |
| world_facts 重复率 | 高（同一 kitchen 描述多次） | < 20% |
| 任务模板覆盖率 | 无 | boil/freeze/melt 均有 task_template |
| Phase2 初始检索质量 | 返回“go to kitchen” | 返回“complete_boil_substance”策略链 |

---

## 六、总结

当前 BIAgent 的低层级问题不是单点缺陷，而是 **Phase1 探索策略鼓励广度覆盖 → scene 表示稀疏 → prompt 强制具体 → graph 基于字符串合并 → curiosity 奖励地点发现** 这一整条链路共同导致的。agent 被系统性地推向“去新房间、开门、看几眼”这种最简单、最安全、最容易获得 curiosity 奖励的行为，而回避“把物质放进热源/冷源验证因果”这种高风险但高信息量的实验。改进必须从最上游的探索策略入手，配合 reflection prompt、scene 结构化、graph 归一化与 consolidation，最终形成可迁移的 domain theory。只要让系统开始奖励和固化“抽象、因果、组合、可验证”的认知，就能从“记录轨迹”升级为“学习世界”。
