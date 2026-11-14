## BIAgent

### BIAgent方法概览

Phase 1 以探索为目标，并伴随着 world graph 生成 -> 反思生成 skill graph -> Phase 2 以完成任务为目标，基于局部的reward来完善 world-skill graph  每个游戏或任务都重复phase1和phase2两个阶段

#### Phase 1：Curiosity-driven domain exploration

在一个特定领域中，agent 不急着完成当前任务，而是先去建立：

- **情景记忆（scene / episode）**

由探索产生的原始输出日志切分为多个场景（scene），一个 scene 里同时包含两类信息：

- 关于世界的：时间、地点、对象、状态变化、因果线索、环境约束
- 关于技能的：在这种条件下采取了什么操作、顺序如何、结果如何、何时失败

- **世界模型：实体、状态、状态转移..**
  - 领域里存在什么对象/状态，预测执行某个动作后的状态转移（如果从记忆角度也可以是 Factual Memory 或者说 Semantic Memory
- **技能模型：precondition，postcondition，成功路径，失败总结，评分..**
  - 通过什么程序化手段把状态从 A 变到 B（如果从记忆角度讲故事就是 Experiential 或者 Procedural memory
- **Curiosity = 世界&技能模型中知识结构生长的收益**
  - 某个动作之所以值得探索，不是因为它单纯新奇，而是因为它能为世界模型&技能模型添加新的信息
  - 好奇心用于判定每个情景是否值得记录和写入，在轨迹切分为 scene 之后，对每个 scene 打分，决定是否写入、是否触发反思，是否蒸馏生成世界模型和技能模型。
  - 直到好奇心驱动产生的情景记忆对于世界模型和技能模型的信息增量饱和时，agent停止探索

#### Phase 2：Task-conditioned solving

 当具体任务到来时，不再从零搜索，而是把任务映射到

- 世界模型中的目标状态或子图
- 技能模型中的候选策略链

### 机制细节

#### phase1: 探索阶段循环机制

Phase1 的目标不是完成某个具体任务，而是在给定预算内，将可复用信息增量最大化，当信息增量饱和时，即可停止探索。某个动作之所以值得探索，不是因为它单纯新奇，而是因为它能为 graph 添加新的信息，或减少两图之间的不一致

- world model 的增长
- skill model 的增长
- 高价值 scene memory 的积累（这里 scene 只是中间载体，不作为独立资产计入停止条件）

##### 以 exploration chunk 为单位循环

每个 chunk 结束后：

1. 从最近轨迹中切分出新 scene
2. 计算 scene 的 curiosity
3. 对高价值 scene 做反思与蒸馏
4. 更新 world / skill model
5. 统计本 chunk 的资产增量
6. 若最近若干 chunk 的平均增量低于阈值，则停止

停止条件，满足以下任一：

- 达到最大探索预算
- 最近 N 个 chunk 中平均信息增量低于阈值
- 最近 N 个 chunk 中平均 curiosity 很低
- 连续落入已知失败边界或重复区域

##### 信息增量计算

$$[ \Delta A_t^{cur} = \sum_{s \in \mathcal{S}t} \mathbf{1}[Curiosity(s)\ge \theta{reflect}] \cdot (\alpha \Delta W(s) + \beta \Delta S(s)) ]\\  (\Delta A_t^{cur})：由好奇心驱动产生的信息增量\\ (\Delta W(s))：该 scene 带来的 world 增量\\ (\Delta S(s))：该 scene 带来的 skill 增量\\  停止条件： [ \frac{1}{N}\sum_{i=t-N+1}^{t}\Delta A_i^{cur} < \epsilon ]\\ 即： 最近 (N) 个窗口里,由高 curiosity scene 带来的平均信息增量,低于阈值时停止$$

##### 冷启动：好奇心与资产增量的早期估计

在探索初期，world model 和 skill model 还很弱，很多依赖它们的值无法稳定计算，因此设计一个冷启动机制。总体原则是：先用可直接从 scene 本身得到的启发式信号驱动写入与反思，随着 world/skill 逐步形成，再切换到依赖模型的完整计算。

- 在冷启动阶段，`Curiosity(scene)` 主要由 `Novelty`、`Coverage`、`Distillability` 决定；
- `ExceptionBonus` 在 world model 尚不足以做可靠预测时，不直接使用“违反 world 预测”来定义，退化为：
  - 是否出现明显 error / exception
  - 是否出现成功/失败转折
  - 是否出现和前文 observation 明显不一致的状态变化
- 信息增量在冷启动阶段也采用近似定义，不要求 scene 一定已经完成高质量 world/skill 蒸馏，而是用以下 proxy 估计：
  - 新增高 curiosity scene 数量
  - 新增实体 / 地点 / 关系候选数
  - 新增可蒸馏 skill 候选数
- 当 world model 中已有足够数量的稳定节点/规则，且已有一定数量的 skill 文档后，再切换到完整定义：
  - `ExceptionBonus` 由“是否违反 world model 预测”计算；
  - `ΔW(s)` 和 `ΔS(s)` 由真实写入后的 world/skill 增量计算。

冷启动阶段采用启发式 curiosity + 近似资产增量，中后期采用模型驱动 curiosity + 真实资产增量。这样可以避免在探索初期因为 world/skill 过弱而导致好奇心和停止条件失效。

#### **phase1: 情景记忆（scene）**

**将** **log** **切分并解析成 scene**

##### 字段结构：

```Python
Scene = {
  # 1. 标识信息
  "scene_id": str,
  "trajectory_id": str,

  # 2. 时空与上下文
  "when": {
    "start_step": int,
    "end_step": int
  },
  "where": str,                    # 当前场景的主地点/页面/区域
  "entities": List[str],           # 当前场景涉及的关键对象
  "context": str,                  # 当前子目标/任务上下文
  "segment_reason": str,           # 为什么在这里切出 scene

  # 3. 场景前后状态
  "state_before": {
    "location": str,
    "inventory": List[str],
    "goal_context": str | None,
    "known_map": Dict[str, Dict[str, str]] | None,
    "entities": Dict[str, Dict] | None,
    "constraints": List[str] | None,
    "open_hypotheses": List[str] | None
  },
  "state_after": {
    "location": str,
    "inventory": List[str],
    "goal_context": str | None,
    "known_map": Dict[str, Dict[str, str]] | None,
    "entities": Dict[str, Dict] | None,
    "constraints": List[str] | None,
    "open_hypotheses": List[str] | None
  },

  # 4. 场景结果
  "outcome": str,                  # 这一段整体发生了什么、得到什么结论

  # 5. 场景内关键事件
  "events": [
    {
      "step": int,
      "action": str,
      "observation_before": str,
      "observation": str,
      "feedback": str | None
    }
  ],

  # 6. 状态与评估
  "status": {
    "steps_taken": int,
    "done": bool | None,
    "won": bool | None,
    "lost": bool | None,
    "current_score": float | None,
    "best_score": float | None
  },
  "metrics": {
    "curiosity_score": float | None,
    "novelty_score": float | None,
    "coverage_score": float | None,
    "exception_bonus": float | None,
    "distillability_score": float | None,
    "is_success": bool | None
  },

  # 7. 反思
  "reflection": {
    "summary": str | None,
    "distillable": bool | None
  }
}
```

一个具体示例如下：

```JSON
手动做了一个例子，gpt 5.4 thinking：
{
  "scene_id": "sc_awaken_dog_patrol_01",
  "trajectory_id": "traj_awaken_20260308_142348",

  "when": {
    "start_step": 5,
    "end_step": 9
  },
  "where": "Church Perimeter",
  "entities": ["church", "dog", "chain", "ivy"],
  "context": "bypass_guard_dog_and_find_church_entry",
  "segment_reason": "encountered major obstacle and discovered dog patrol mechanism",

  "state_before": {
    "location": "Front of the Church",
    "inventory": ["limb"],
    "goal_context": "enter church",
    "known_map": {
      "Graveyard": {
        "east": "West Side of the Church"
      },
      "West Side of the Church": {
        "southeast": "Front of the Church",
        "northeast": "East/North route"
      }
    },
    "entities": {
      "dog": {
        "present": true,
        "state": ["hostile"],
        "behavior_hypothesis": null
      },
      "church": {
        "present": true,
        "state": ["front_blocked"]
      }
    },
    "constraints": [
      "avoid attacking dog"
    ],
    "open_hypotheses": [
      "dog patrol can be exploited"
    ]
  },

  "state_after": {
    "location": "North Side of the Church",
    "inventory": ["limb"],
    "goal_context": "enter church",
    "known_map": {
      "Graveyard": {
        "east": "West Side of the Church"
      },
      "West Side of the Church": {
        "southeast": "Front of the Church",
        "northeast": "East Side of the Church"
      },
      "Front of the Church": {
        "northeast": "East Side of the Church",
        "northwest": "North/West path"
      },
      "East Side of the Church": {
        "northwest": "North Side of the Church"
      }
    },
    "entities": {
      "dog": {
        "present": false,
        "state": ["chained", "hostile"],
        "behavior_hypothesis": "follows to east side and returns to front when player reaches north side"
      },
      "chain": {
        "present": true,
        "state": ["sturdy", "cannot_break_easily"]
      },
      "ivy": {
        "present": true,
        "state": ["exists", "possibly climbable"]
      }
    },
    "constraints": [
      "avoid attacking dog",
      "non-violent bypass is preferred"
    ],
    "open_hypotheses": [
      "ivy route may be testable",
      "alternate entrance may exist behind or above the church"
    ]
  },

  "outcome": "The agent discovered that the guard dog is chained, can be drawn to the east side, and then returns to the church front when the player reaches the north side. This reveals a possible non-violent bypass mechanism and suggests that the north side may provide an alternative route into the church.",

  "events": [
    {
      "step": 5,
      "action": "southeast",
      "observation_before": "West Side of the Church",
      "observation": "Front of the Church ... A formidable looking guard dog stands here.",
      "feedback": "The dog growls at you threateningly."
    },
    {
      "step": 6,
      "action": "examine dog",
      "observation_before": "Front of the Church with dog present",
      "observation": "This large, solid black dog is chained to one of the oak trees.",
      "feedback": "The dog growls at you threateningly."
    },
    {
      "step": 8,
      "action": "northeast",
      "observation_before": "The dog is chained and still threatening.",
      "observation": "East Side of the Church ... the dog follows you to the East Side of the Church, dragging its chain behind it.",
      "feedback": "Dog follows to east side."
    },
    {
      "step": 9,
      "action": "northwest",
      "observation_before": "East Side of the Church with dog following",
      "observation": "North Side of the Church ... Satisfied, the dog wanders off back to the Front of the Church.",
      "feedback": "Dog returns to front."
    }
  ],

  "status": {
    "steps_taken": 4,
    "done": false,
    "won": false,
    "lost": false,
    "current_score": 0.0,
    "best_score": 0.0
  },

  "metrics": {
    "curiosity_score": 0.84,
    "novelty_score": 0.71,
    "coverage_score": 0.79,
    "exception_bonus": 0.90,
    "distillability_score": 0.93,
    "is_success": true
  },

  "reflection": {
    "summary": "This scene reveals a reusable obstacle mechanism: the dog is not solved by force but by exploiting its chained patrol behavior. The scene is suitable for distilling both a world rule about dog movement and a skill for bypassing the church-front obstacle.",
    "distillable": true
  }
}
```

##### 切分规则

LLM辅助进行log的切分，按照以下规则将log切分为若干scene，切分规则的优先级由LLM进行动态规划

1. exception
   1. 动作失败、错误返回、明显偏离预期、LLM 或规则判定为异常现象
   2. curiosity 最相关，（环境返回 error/exception)
2. 地点切换
   1. 页面 URL、环境区域、工作目录等发生明确变化
3. 任务子目标切换
   1. LLM 规划或规则判断“进入下一子目标”
4. 动作序列闭环
   1. 检测到“搜索→选择→购买”等典型模式完成，或连续 N 步无状态变化后结束
5. 主体切换
   1. 主要操作对象或工具类型切换
6. 状态显著变化
   1. `state_before` 与 `state_after` 的差异超过阈值（embedding 距离、关键字段变化等）
   2. 每 K 步或 embedding 变化超过阈值时切分
   3. 

#### phase1: 好奇心（curiosity）

##### 计算方法

scene切分完成后，对每个scene进行好奇心的计算，由好奇心驱动，逐步写入有价值的scene memory并构建世界模型和技能模型的图结构。

| 维度                       | 直觉                            | 计算思路                                         |
| -------------------------- | ------------------------------- | ------------------------------------------------ |
| Novelty（新奇度）          | 和已存 scene 的相似度越低越好奇 | 1 − max(与已存 scene 的 embedding 相似度)        |
| Coverage（覆盖度）         | 拓展认知地图、填补空白的程度    | 新实体/地点/关系数 ÷ 该 scene 总元素数           |
| ExceptionBonus（异常加成） | 实际结果与预期不符的程度        | 若 outcome 违反 world model 预测则为 1，否则为 0 |
| Distillability（可蒸馏性） | 能否归纳为可复用的规则或技能    | LLM 或启发式评分 (0–1)                           |

$$Curiosity(scene) = α·Novelty + β·Coverage + γ·ExceptionBonus + δ·Distillability$$

Novelty 和Coverage可能存在维度重叠，可考虑在在计算的时候去冗余

##### 写入与反思规则

1. $$ Curiosity < θ_{write}$$，不写入，不反思
2. $$θ_{write} ≤ Curiosity < θ_{reflect}$$，写入 scene memory，不触发深度反思
3. $$Curiosity ≥ θ_{reflect}$$，写入 scene memory，并触发反思与蒸馏(→ world model / skill model)

可参考的反思内容：

- 因果归因：谁/在什么条件下/执行了什么操作/导致什么结果
- 世界知识：列出0-3条可泛化事实，格式：若[条件]则[结论]
- 技能：若存在可复用流程或技能，给出激活条件、核心步骤、终止条件、风险点等内容
- 提出开放问题：仍不确定、需更多证据的问题……

#### phase1: Graph-structured World / Skill Model 双图检索

World Model 和 Skill Model 都是多层级的图结构，从而实现 round-level progressive exposure，而不是一次性加载 top-k 个 skill 文档塞到 prompt 这种静态注入的做法

##### **从 scene 提取 world** **graph**：

Agent 在环境探索的过程 = 不断发现新的 entity / state，并完善它们之间转移关系的过程，即构建世界模型，实现环境认知建模

###### 结构

世界模型定义：当前状态 + 动作 → 未来状态

我们可以从observation, state, action中保存state并抽取entity，将action作为状态转移算子

1. 节点：entity，state
2. 边：transition edge（state → state 描述状态转移），containment edge（state ↔ entity 状态中包含哪些实体），edge（state，action → episodic item 来自哪些经历）
3. 规则层（if-then + 可选链到节点），图难以表达精细 if-then，所以用规则表进行补充【规则层可省略，将规则纳入节点的“属性”字段】
   1. if`/`condition：自然语言或半形式化条件
   2. then`/`consequence：结果或约束
   3. source_scene_ids
   4. links：指向图中相关节点 id，便于检索

![img](https://wcnjl7wdeayh.feishu.cn/space/api/box/stream/download/asynccode/?code=MjhlZTViYzI2MzYyNTBhN2NjY2RiMzdlOWQ1NzE0NTlfRjZJMlMzMXFZVG94WmRJR2h1bjZkcUVlQ1VDRFRKZmFfVG9rZW46UmtjWGJpRmREb3lSdGJ4U2ZXbGNHdDVnbk1nXzE3NzQ1Mzc0MTM6MTc3NDU0MTAxM19WNA)

推理时对 world graph 的检索：entity关键字，state向量相似度

高层节点（entity）可以做 routing signal，去索引低层节点（entity->state）

###### 蒸馏过程

输入LLM：一个或多个 scene（仅超过好奇心阈值的） + 当前世界模型摘要

输出：new_nodes，new_edges，new_rules

合并与写入

- 节点：id 已存在则合并属性或更新置信度，不存在则追加
- (src, dst, rel) 相同则合并边上的说明或置信度
- 规则：每条分配id并写入规则库
- 去重：新规则和新节点与已有规则做语义相似度，过近则合并

##### **从 scene 提取 skill** **graph**

###### 结构

skill 文档是 skill model 的主存储形式

- 每个 skill 以独立文档保存，延续现有 `skill.md` 的设计
- skill 的粒度不面向整个任务，而是面向当前子目标或局部可复用过程
- skill 文档可包含字段：`activation / precondition / postcondition / execution / risks / 失败总结 / 评分 / related_world_fact_ids`

skill graph 只是索引层，不是主表示层

- 不承担完整内容存储，只保留轻量的索引与连接关系
- 主要节点：`subgoal`，`skill`
- 主要边：
  - `subgoal → skill`：某个子目标可调用哪些 skill
  - `skill ↔ skill`：skill 之间的引用、补充或相邻关系
  - `skill → scene`：该 skill 来自哪些 supporting scenes
  - `skill → world fact`：该 skill 依赖哪些 world rules / facts

检索方式

- 以 `subgoal` 关键字 + 向量相似度做 coarse retrieval
- 再通过 graph 中的轻量连接关系，将候选 skill 扩展到相关 skill、supporting scenes 和 related world facts
- 高层节点（如 `entity / subgoal`）可以作为 routing signal，去索引更底层的 skill 文档内容

###### 蒸馏过程

每次输入一个或多个高 curiosity 的 scene，先确定 world model 的增量，再生成或更新 skill。

输入

- 一个或多个高价值 scene
- 当前 world model 摘要或相关规则
- 已有 skill 索引（如 `title + activation` 摘要），用于避免重复生成

输出

- 新的 skill 文档，或对已有 skill 文档的 patch/update

蒸馏流程

1. 从 scene 中抽取当前子目标下可复用的操作模式
2. 生成 skill 的核心内容：适用条件、关键步骤、终止条件、风险点
3. 将该 skill 与当前 world facts 建立显式关联
4. 写入 skill 文档，并同步更新 skill graph 的索引关系

合并与写入

- 去重：与已有 skill 做 embedding 相似度匹配，相似则 patch，而不是重复新建
- patch 的内容可包括：增补步骤、补充失败边界、修正 activation / termination、更新评分
- 互链：将本次蒸馏产生的 world rule id 写入 skill 文档的 `related_world_fact_ids`
- graph 同步更新：补充 `subgoal → skill`、`skill → scene`、`skill → world fact` 等轻量边关系

##### **关联 world** **graph** **与 skill graph，实现跨图推理：**

skill 本身就是 world graph 上的局部状态转移假设

 $$Φ:(skill.pre,skill.post)↔world \; subgraph$$

- 每个 skill 的 precondition，映射到 world graph 里的某个 state
- 每个 skill 的 postcondition，映射到 world graph 里的状态变化的子图
  - ![img](https://wcnjl7wdeayh.feishu.cn/space/api/box/stream/download/asynccode/?code=MTE3YWVlZGEyODcyOThlMTY3NTQ0ZmMwYmY0ZWM2YmFfRm9odkt2aVkwOEVXM09iT3MwSE9JeVQwMkJNR2hodGVfVG9rZW46WXZjMGJjZ1FMb3V2VFV4TTlZSGNtdWxFbmhiXzE3NzQ1Mzc0MTM6MTc3NDU0MTAxM19WNA)

在推理时 Agent 是基于 current observation 和 action space（自然语言描述，比如"Front of the Church ... A formidable looking guard dog stands here."，["northeast", "northwest"...]），通过:

- 在高层节点以keyword检索 `entity(dog) & subgoal(inspect_guard_dog)`，
- 在底层节点直接以embedding检索 `state & skill`
- graph-conditioned retrieval：在 world graph 找到匹配的局部子图，再找所有 `precondition` 与该子图匹配的 skill

#### phase2: 检索

- Stage 1：尽可能沿用现有的skill.md的结构，还是以文本文件来构建skill文档和graph，测试够用了（由于Jericho每个子任务是一个域，world graph的entity node也就十多个，state node不过百，还不太需要数据库搞索引；如果做minecraft，子任务之间是相通的，图就会很大
- Stage 2：可以考虑轻量的索引（SQLite + 向量索引）
- Stage 3：拓展到 Neo4j 等图数据库....
- ....

**文件层**：`skill.md`内部字段先保持现状（多维技能库也ok），补`episodic.jsonl / world_graph.json / skill_graph.json`

**索引层**：额外建一个轻量数据库或索引文件，专门做召回

**推理层**：沿用 `query_skill`，但从直接检索 skill.md 升级成先做图索引，再回到 skill.md/episode 取证据

```JSON
memory_store/
    jericho/ （dataset）
        JerichoEnvAwaken/ （env_name，域）
            raw/ （保留原始log）
                manager.log 
            parsed/
                episodic_items.jsonl ([list]规则解析+LLM consolidation成episodic items，实时更新
                segments.jsonl ([list]按照subgoal对items进行聚合，搭建segment中间层
            reflections/ （对聚合后的episodic_items做skill summary，中间结果）
                run_summary_1
                ...
            graphs/ （存结构化图）
                world_graph.json
                skill_graph.json
                skills/
                    skill_xx.md
                    skill_yy.md
                grounding_links.json
            index/ （存索引：元数据表、embedding 索引、倒排索引、召回缓存）
                metadata.sqlite
                state_vectors.faiss
                skill_vectors.faiss
            
        
    crafter/ （dataset，域）
        raw/
            manager.log
        parsed/
            episodic_items.jsonl
            segments.jsonl
        reflections/
        graphs/
        index/
```

##### query_skill 的设计

1. **routing / coarse retrieval**

   1.  输入是：current observation、admissible actions、env_name、dataset

   2.  **dataset/****env** **过滤 → entity keyword 检索 → subgoal keyword 检索 → usage_conditions 过滤**

   3. 还是以 JerichoEnvAwaken 为例

      current obs 出现 `dog`、`church`、`front`，就先把候选限制在：

      - `dataset = Jericho, env_name = JerichoEnvAwaken`
      - entity 包含 `dog`
      - entity **→** subgoal 接近 `inspect_guard_dog` / `dog_obstacle`

1. **graph-conditioned retrieval**

先查 world graph，根据 current state，找最相似或最匹配的 world state node：

> - `Front of the Church`
> - `dog present`
> - `entry blocked`

再查 grounding links，找到所有 precondition 对应到该 world subgraph 的 skills

也就是

 $$Φ:(skill.pre,skill.post)↔world \; subgraph$$

然后设计排序分数

$$score(skill)=α⋅pre\_match+β⋅quality$$

1. **skills** **/** **evidence expansion**

选中的 top-k skill，并基于选中的 skill 节点进行扩展：

- [skill **→** skill] 关联的 skill nodes（因为我们 skill 是服务于当前 subgoal，内部 `ref` 可能引用了相关的 skill）
- 选择性 [skill **→** episodic items] 支撑的 episodic segments（即原始 log 证据） 
- 选择性 [skill **→** skill.pre,skill.post **→** state] 对应的 world state / transition 边