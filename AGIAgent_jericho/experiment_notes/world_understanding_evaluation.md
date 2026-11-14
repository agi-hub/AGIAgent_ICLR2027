# World Understanding Evaluation（WUE）评价基准

## 1. 背景与动机

当前 ScienceWorld 等交互式 benchmark 几乎完全以**任务完成率**作为唯一成功标准。这种评价方式隐含了一个假设：能完成任务的 agent 就是更好的 agent。

但这一假设存在问题：
- agent 可能只记住了一条成功路径，对环境缺乏真正理解；
- 完成任务不一定需要探索环境的全部结构；
- 无法衡量 agent 的泛化能力、可解释性和迁移潜力。

因此，我们提出 **World Understanding Evaluation（WUE）**：一套专门评价 agent 在 phase1 探索阶段所构建的**世界模型质量**的基准，而不是评价 phase2 的任务完成度。

---

## 2. 核心思想

> **探索的价值 = agent 构建的内部世界模型与真实环境之间的对齐程度。**

一个真正理解世界的 agent，应该能够：
- 说出环境里有什么对象、地点；
- 说出对象之间有什么关系；
- 预测动作会产生什么效果；
- 解释失败原因；
- 将知识迁移到未见过但结构相似的任务。

WUE 通过对比 agent 的资产文件与 ScienceWorld 的真实对象树（`getObjectTree()`），量化这种理解深度。

---

## 3. 评价维度

WUE 包含 8 个评价维度，每个维度下设若干可量化子指标。

### 3.1 结构覆盖率（Structural Coverage）

衡量 agent 发现了多少环境的静态结构。

| 子指标 | 定义 |
|--------|------|
| 地点覆盖率 | agent 访问过的房间数 / 环境总房间数 |
| 对象发现率 | agent 见过/交互过的对象数 / 环境总对象数 |
| 对象类型覆盖率 | 发现的对象类型数 / 218 种总类型 |
| 容器发现率 | 发现的容器数 / 总容器数 |
| 出口/门覆盖率 | 发现的房间连接数 / 总连接数 |

### 3.2 关系发现率（Relational Coverage）

环境不是对象集合，而是关系网络。

| 子指标 | 定义 |
|--------|------|
| 空间包含关系 | 发现的 `A 在 B 里` 关系 / ground truth 包含关系 |
| 房间连通关系 | 发现的门/出口关系 / 实际连通关系 |
| 可交互关系 | 尝试过的（动作，对象）对 / 当前状态下合法的对 |

### 3.3 动态预测准确率（Dynamic Prediction）

agent 能否预测动作后果，是"理解"的核心。

| 子指标 | 定义 |
|--------|------|
| 状态变化预测准确率 | 预测正确的属性变化数 / 总变化数 |
| 前提条件判断准确率 | 正确判断动作当前是否合法的比例 |
| 失败预测准确率 | 正确预测动作会失败的比例 |

**测量方式**：从合法动作组合中采样探针，用 agent 的世界模型预测结果，再与真实 `env.step()` 对比。

### 3.4 因果规则完备性（Causal Rule Completeness）

agent 是否提炼出正确的因果规则。

| 子指标 | 定义 |
|--------|------|
| 规则精确率 | `world_graph.rules` 中正确的规则数 / 总规则数 |
| 规则召回率 | ground truth 关键因果事实被规则覆盖的比例 |
| 规则泛化性 | 规则是否使用抽象概念而非具体对象名 |

### 3.5 Affordance 理解（Action Affordance Understanding）

agent 是否知道什么对象能做什么。

| 子指标 | 定义 |
|--------|------|
| affordance 覆盖率 | agent 知道的可行动作对 / 实际可行动作对 |
| affordance 错误率 | agent 认为可行但实际不可行的动作比例 |
| 动作效果正确率 | agent 对 affordance 效果的描述正确率 |

### 3.6 任务无关 Skill 发现（Task-Agnostic Skill Discovery）

agent 发现的 skill 是绑定到具体任务，还是可迁移。

| 子指标 | 定义 |
|--------|------|
| skill 抽象度 | skill 中使用抽象类（container/heat source）的比例 |
| skill 可复用性 | 同一 skill 可用于相关任务的比例 |
| skill 执行完整性 | skill 的 core_steps 是否包含完整动作链 |
| 新 skill 发现率 | 每 100 轮探索发现的可复用 skill 数 |

### 3.7 探索效率（Exploration Efficiency）

理解同样的世界，用的步数越少越好。

| 子指标 | 定义 |
|--------|------|
| 单位步数覆盖率 | 地点覆盖率 / 总步数 |
| 单位步数规则数 | 正确规则数 / 总步数 |
| 饱和步数 | 达到 90% 关键覆盖所需的步数 |
| 重复动作比例 | look around / inventory 等低信息动作占比 |

### 3.8 模型一致性与可解释性（Model Coherence）

agent 的世界模型内部是否自洽、可读。

| 子指标 | 定义 |
|--------|------|
| 规则冲突数 | world_graph 中互相矛盾的规则数 |
| 实体一致性 | 同一对象在不同 scene 中是否有矛盾描述 |
| 模型压缩率 | 用多少 scene/rule/skill 覆盖了多少环境信息 |
| 人类可读性 | skill markdown 是否可被人类理解并执行 |

---

## 4. 综合评分

各维度加权汇总为 WUE Score：

```python
WUE_score = (
    0.15 * structural_coverage +
    0.15 * relational_coverage +
    0.20 * dynamic_prediction_accuracy +
    0.15 * causal_rule_completeness +
    0.10 * affordance_understanding +
    0.10 * task_agnostic_skill +
    0.10 * exploration_efficiency +
    0.05 * model_coherence
)
```

权重可根据研究目标调整：
- 关注物理理解：提高 dynamic_prediction 和 causal_rule 权重；
- 关注泛化：提高 task_agnostic_skill 权重；
- 关注效率：提高 exploration_efficiency 权重。

---

## 5. 与任务完成率的区别

| 对比项 | 任务完成率 | WUE |
|--------|-----------|-----|
| 评价阶段 | phase2 结束后 | phase1 结束后即可评价 |
| 评价对象 | 求解能力 | 世界理解能力 |
| 是否依赖任务目标 | 是 | 否（任务无关） |
| 是否可解释 | 弱（只有 success/fail） | 强（覆盖哪部分、缺哪部分） |
| 是否鼓励泛化 | 否 | 是 |
| ground truth | 任务完成信号 | 环境对象树 + 物理规则 |

---

## 6. 实施路径

### 6.1 Ground Truth 提取

从 `ScienceWorldEnv.getObjectTree()` 提取：
- 房间列表
- 对象列表及类型
- 对象属性
- 包含关系
- 房间连通关系
- 合法动作组合

### 6.2 Agent 世界模型读取

读取 BIAgent phase1 资产：
- `parsed/episodic_items.jsonl`
- `graphs/world_graph.json`
- `graphs/skill_graph.json`
- `reflections/*.json`

### 6.3 动态探针

在 phase1 结束后，用 agent 的世界模型回答动作预测问题，并与真实环境执行结果对比。

### 6.4 输出报告

输出各维度分数、综合 WUE Score、以及详细 breakdown（例如哪些房间没去过、哪些对象没发现、哪些规则错误）。

---

## 7. 意义与局限

### 意义

1. **鼓励真正的探索**：agent 有动力去理解环境全貌，而不是只找一条成功路径；
2. **可解释性增强**：能明确说清 agent 理解了什么、没理解什么；
3. **跨任务迁移可量化**：任务无关 skill 和因果规则可直接作为迁移指标；
4. **与人类认知对齐**：人类学习也是先建立世界模型，再解决具体问题。

### 局限

1. **评估成本高**：动态探针需要大量真实环境交互；
2. ground truth 虽然是对象树，但"理解"本身是开放概念，指标设计存在偏差；
3. 完整覆盖世界可能需要远多于任务完成的步数，与 benchmark 效率目标存在张力。

---

## 8. 相关文件

- 本文档：`world_understanding_evaluation.md`
- 评价脚本：`apps/scienceworld/world_understanding_evaluator.py`
