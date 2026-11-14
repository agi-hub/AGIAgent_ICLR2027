# FRAME 提案可行性分析

> 基于 AGIAgent_jericho 代码库与 abl11-abl14 实验数据的评估
>
> 日期: 2026-07-23

---

## 0. 提案概要

FRAME (Frontier-preserving Rate-Adaptive Memory) 提出"记忆作为压缩层级"的视角，诊断当前缓存式记忆系统存在"探索坍缩"问题（知道得越多、越不去看新东西），并设计三级压缩记忆架构（语义规则 S / 世界模型图 G / 原始经验 E）配合知识不确定性驱动的前沿回退来解决。

---

## 1. 提案的四个观察 — 数据验证

FRAME §3 提出四个观察支撑"探索坍缩"诊断。逐条用实验数据验证：

### O1: 增益主要来自被编译的硬约束，而非探索

**提案声称**: 约 70-80% 来自"即死动作硬拦截"

**我们的数据** (abl12 反事实 FATAL 拦截分析):

| 模型 | 拦截次数 | 挽救分数 | 占总分比例 |
|---|---|---|---|
| GLM-4.7 | 12 | +71.0 / 264.8 | 26.8% |
| DeepSeek-Pro | 4 | +14.2 / 362.7 | 3.9% |
| GLM-4.7 Deephome | — | 54.9 / 67.3 | **81.6%** |

**判定: ✅ 成立。** 在即死陷阱主导的游戏上（如 Deephome），硬约束贡献了绝大部分分数。GLM 整体比例低于提案的 70-80%，但这是因为 GLM 的基础得分（knowledge 检索利用）也占有一定份额。

### O2: 知识在长，表现不长 (knowing-doing gap)

**提案声称**: 得分趋势不显著上升，方差极大

**我们的数据** (abl14_glm_full Detective):

- 单局得分: 20, 200, 310, 80, 310, 310, 210, 310, 210, 310
- 变异系数 (CV): 0.90
- 10 次迭代中 6 次达到 200+，但仍有 1 次只有 20 分

**判定: ✅ 成立。** 确定性环境下如此大的方差只能归因于知识取用不稳定——同样的 knowledge 文件，有时被有效部署（310 分），有时完全没有起作用（20 分）。

### O3: 知识有时压制探索（锚定）

**提案声称**: 带知识不如无知识

**我们的数据** (abl13_glm_no_knowledge vs abl11_glm_full):

| 游戏 | full avg | no_knowledge avg | 差值 |
|---|---|---|---|
| Detective | 92.0 | **128.0** | **+36.0** |
| Library | 25.1 | 21.3 | -3.8 |
| Zork1 | 43.5 | **47.2** | **+3.7** |
| Temple | 13.2 | 12.2 | -1.0 |

**判定: ✅ 成立。** Detective 上 no_knowledge (128.0) 显著高于 full (92.0)。Knowledge 把 agent 钉死在已知路径上，抑制了自由探索。

### O4: 前沿与原始经验从未被用

**提案声称**: "Unexplored"段是死文本；experience 库几乎不被检索

**我们的数据** (abl14_glm_full):

- wiki_memory_read 总查询: 277 次
- 查 knowledge section: 273 次 (98.6%)
- 查 experiences section: 4 次 (1.4%)
- agent 跟随 experience 链接: **0 次**
- knowledge 文件中 "Unexplored" 段的查询命中率: 接近 0

**判定: ✅ 成立。** experience 文件和 "Unexplored" 段都是死数据。

### 小结

四个观察全部被实验数据支撑。FRAME 的问题诊断是准确的——当前系统确实是一个"只服务利用与避坑的缓存"，探索前沿被压缩丢弃，原始经验无法被寻址。

---

## 2. 现有代码 vs FRAME 三级架构

```
FRAME 理想架构           当前代码                差距
─────────────────       ─────────────────       ──────────
S 语义规则 (高压)        knowledge/*.md          ≈ 已有，无 G 指针
G 世界模型图 (中压)       不存在                  ❌ 核心缺失
E 原始经验 (无压)        experiences/*.md        ≈ 已有，append-only
S→G→E 解压指针           knowledge→experience    ⚠️ 有 S→E 链接，无 G 中间层
```

### 关键代码位置

| 组件 | 文件 | 行号 | 现状 |
|---|---|---|---|
| S 语义规则 | `data/wiki/{exp}/knowledge/*.md` | — | 每 <800 词，phase_m 重写 |
| E 原始经验 | `data/wiki/{exp}/experiences/DATE/*.md` | — | append-only，phase_m 追加 |
| S→E 链接 | `apps/tale_jericho/prompts/phase_m_prompt.txt` | 42-51 | Evidence: [Attempt N](path) |
| wiki_memory_read | `src/wiki_memory.py` | 420-653 | embedding 检索，max_results=3，返回完整内容 |
| FATAL 拦截 | `src/tools/tale_jericho_tools.py` | `_check_fatal_action()` | 房间匹配 + 导航词保护 |
| Loop 检测 | `src/tools/tale_jericho_tools.py` | 282-309 | (action, room) 对，>=5 触发 |
| Loop hint | 同上 | 296-309 | 带未试命令建议 |
| 状态保存/恢复 | `jericho.FrotzEnv` | get_state/set_state | **存在但从未调用** |
| admissible_commands | `src/tools/tale_jericho_tools.py` | 336 | 每步返回，完整不截断 |

---

## 3. 各组件可行性分析

### ✅ 可做 — 底层能力已具备

#### 3.1 O(1) 状态回退

Jericho 底层库 `jericho.FrotzEnv` 原生提供 `get_state()` / `set_state()` 方法，返回二进制状态 blob，可 O(1) 保存和恢复。

Wrapper 链: `gym.make → tales.JerichoEnv → textworld.TWJerichoEnv → FrotzEnv`

**当前代码从未调用过这些方法**。`TaleJerichoTools` 只用了 `env.reset()`、`env.step()`、`env.close()`。

textworld 层也有 `copy()` 方法（返回 env 副本）和 `load(z_file)` 方法（从文件恢复）。

`src/tools/textquests_tools.py` (L122-167, L686-734) 有完整的 checkpoint/restore 系统作为参考实现。

**实现需要**: 通过 wrapper 链获取底层 FrotzEnv (`session["env"].unwrapped.env.env`)，或添加 wrapper 方法暴露 state 接口。

#### 3.2 admissible_commands → 前沿计算

`admissible_commands` 每步都从 `info` 返回（L336），包含当前所有合法动作。`untried = admissible - tried` 可直接计算。

Loop detection 已经在追踪 `(action, room)` 对，扩展为节点级 tried 集合是直接增量。

#### 3.3 房间签名

当前 loop detection 已经用 observation 第一行作为 room signature（L286-287）。可直接复用为 G 节点的 `sig(o)`。

#### 3.4 持久化

现有 wiki 目录结构可直接扩展:

```
data/default/general/wiki/{experiment}/
  knowledge/       # S 层
  experiences/     # E 层
  graph/           # G 层 (新增)
    {gamename}.json
```

JSON 序列化图结构，phase_m 时更新。

### ⚠️ 有风险 — 工程量大但可做

#### 3.5 世界模型图 G 的构建

需要新增组件，在每个 `tale_jericho_action` 调用时自动维护:

1. 解析当前 room signature
2. 记录 `(room, action) → (result_room, score_delta, died?)`
3. 更新 `untried = admissible - tried`
4. 保存 `get_state()` 快照到节点
5. 维护节点状态: `frontier` / `exhausted` / `dead`

**问题 — 状态签名粒度**:

纯房间名不够（同一房间，门开关状态不同，行为不同）。但加入 inventory/door state 会过度碎片化。这是 FRAME 自己也承认的"主要工程风险"。

建议: 先用纯房间名（observation 第一行），遇到"同房不同状态"问题再逐步加入关键状态位。

#### 3.6 自动化回退（轮内）

FRAME 的核心卖点——"轮内即触发回退，不等下一轮"。当前设计是线性单次通关（L135: "single-attempt per phase: no restart"）。

两种实现方案:

**方案 A — 代码自动回退**:

loop detection 判定卡住 → 代码自动 `set_state` 到高 promise 前沿节点 → 继续。LLM 不参与决策，但会看到环境突然变化。

- 优点: 可控、确定性强、绕过 LLM 不听话的问题
- 缺点: LLM 被强制传送后可能困惑，不理解发生了什么

**方案 B — LLM 控制回退**:

新增工具 `tale_jericho_backtrack(target_node)`，让 LLM 决定何时回退到哪。

- 优点: LLM 保持对行为的控制权
- 缺点: LLM 可能不会用（参考 experience 链接 0 次使用的情况）、或乱用

**建议**: 先实现方案 A（代码自动），验证效果后再考虑是否给 LLM 控制权。

### ❌ 存在根本性困难

#### 3.7 三级解压指针 (S→G→E)

理论上优雅，但实践中:

- 当前 S→E 链接刚加，LLM **0 次**使用它
- G 作为中间层需要 LLM 理解"先查 S → S 触发 G 查询 → G 触发 E 解压"的多步流程
- 这对 LLM 的工具链使用能力要求很高，GLM-4.7 可能不够

**建议**: 跳过三级指针。S→E 直连已够。G 作为独立的结构化组件供代码侧自动回退使用，不需要 LLM 通过指针链解压。

#### 3.8 知识不确定性公式

```
promise(v) = w1·U_know(v) + w2·r̂(v) - w3·fatal(v) - w4·cost(v)
```

四个权重 w1-w4 是超参。无梯度系统下，只能靠启发式或网格搜索确定。在 9 个游戏上调 4 个权重很容易过拟合。

**建议**: 用简单启发式替代——按 `untried_count` 降序选前沿节点（即"知识空白最多"的房间优先）。这正好是"不确定性选点"的最简版本，足以做 E2 对照实验。

#### 3.9 完整实验矩阵

提案要求 7 种方法 (B0-B5 + Ours) × 6 种消融 × 9 游戏 × 2 模型 × 10-20 迭代。

总计约 **756-1512 次完整实验**。当前单台机器 + 共享 API 配额无法支撑。

**建议**: 大幅缩减。核心对照:

| 方法 | 代表 | 实验量 |
|---|---|---|
| B0 no-memory | 地板 | 已有 (abl11_no_wiki) |
| B2 缓存式记忆 (现有 full) | 暴露坍缩 | 已有 (abl11_full) |
| Ours FRAME (自动回退) | 抗坍缩 | 需新跑 |
| −不确定性 (随机选点) | 内核对照 | 需新跑 |
| −跨轮持久 (每轮重置 graph) | 持久性对照 | 需新跑 |

即 5 种 × 9 游戏 × 1 模型 × 10 迭代 = 450 次，可控。

---

## 4. 务实实现路径

### Phase 1: 最小可行 — 验证"前沿保留" (1-2 周)

1. 在 session 中构建简单 room graph (dict):
   ```python
   graph = {
     "Lobby": {
       "tried": {"look", "west", "east"},
       "untried": {"north", "examine desk"},
       "state_snapshot": <bytes from get_state()>,
       "score_at_visit": 10,
       "visits": 3,
     },
     ...
   }
   ```

2. loop detection 触发时，不再只给 hint，而是**自动回退**到有最多 untried 动作的房间:
   ```python
   if loop_detected:
       target = max(graph.values(), key=lambda n: len(n["untried"]))
       env.unwrapped.env.env.set_state(target["state_snapshot"])
   ```

3. 记录每次回退前后的 agent 行为，评估 agent 对环境突变的适应能力

4. 对照实验: 有自动回退 vs 无自动回退的探索率 (新状态/百步)

**验证目标**: 自动回退能否提升探索覆盖率、降低打转率。

### Phase 2: 验证"不确定性选点" (1 周)

5. 回退目标选择策略对比:
   - **不确定性**: 按 `untried_count` 降序
   - **随机**: 随机选一个 frontier 节点
   - **分数最高**: 回到得分最高的 frontier 节点 (Go-Explore 式)

6. 这正好是 FRAME 的 E2 对照实验 (知识不确定性 vs 分数/novelty)

**验证目标**: 不确定性选点是否优于分数选点。

### Phase 3: 验证"跨轮持久" (1 周)

7. 将 graph 序列化到 `wiki/{exp}/graph/{game}.json`
8. 下一轮开局时注入到 session，agent 可直接奔向已知高 untried 的节点
9. 这正好是 FRAME 的 E4 对照实验

**验证目标**: 跨轮积累是否带来额外收益。

### 不需要做的

- ❌ 三级解压指针 (S→G→E) — 过度设计，S→E 直连已够，G 供代码侧使用
- ❌ knowledge uncertainty 的信息论估计 — 启发式 (untried count) 已够做对照
- ❌ EvoTest / LPLH / LATS 基线复现 — 工作量巨大且偏离主线
- ❌ MC-DML 式搜索树 — 依赖 rollout，与本框架的"无梯度、低成本"定位冲突

---

## 5. 核心风险

### 最大风险: LLM 对环境突变的适应能力未知

当前数据显示 LLM 对已有信息（experience 链接、loop hint 中的 untried commands）的利用率极低。FRAME 的自动回退方案绕过了这个问题，但引入新风险:

> LLM 被强制 `set_state` 传送回某个房间后，能否理解发生了什么？还是会困惑地继续之前的无效行为？

这需要实验验证，不能假设。Phase 1 的首要目标就是回答这个问题。

### 次要风险: 状态签名粒度

纯房间名可能导致同一房间的不同状态（门开关、物品增减）被合并为一个节点，造成"已试动作"判断错误。

反之，加入过多状态位会导致节点过度碎片化，图变成近似线性序列，失去导航价值。

### 次要风险: API 成本

自动回退会增加 episode 内的有效步数（回退后重新探索），可能需要从 100 轮提升回 150-200 轮才能看到效果。

---

## 6. 与提案的定位差异

| 维度 | FRAME 提案 | 务实实现 |
|---|---|---|
| 记忆层级 | S→G→E 三级指针解压 | S + G + E 并列，G 供代码侧自动回退 |
| 回退触发 | 卡住判定 (结构环 + 瓶颈) | loop detection 扩展 (已有基础) |
| 选点判据 | promise(v) 四因子加权 | untried_count 降序 (最简版) |
| 回退方式 | set_state O(1) 跳转 | 同 |
| 轮内触发 | 是 | 是 |
| 跨轮持久 | 是 | 是 (graph 序列化) |
| LLM 参与度 | 高 (多步指针解压) | 低 (代码自动回退，LLM 只看结果) |
| 实验规模 | 756-1512 次 | ~450 次 (5 方法 × 9 游戏 × 10 迭代) |

务实实现保留了 FRAME 的三个核心主张——**保留前沿、不确定性选点、轮内+跨轮回退**——但砍掉了三级指针、复杂不确定性公式、以及大量外部基线复现。

---

## 7. 总结

| 维度 | 评价 |
|---|---|
| 问题诊断 | ✅ 准确，四个观察全部被数据支撑 |
| 理论框架 | ✅ "压缩层级"视角有解释力 |
| 技术可行性 | ⚠️ 底层能力具备 (get_state/set_state)，但从未接入 |
| 工程复杂度 | ❌ 完整实现量大；三级指针 + 不确定性公式过度设计 |
| 实验可行性 | ❌ 完整矩阵不可行；需大幅缩减 |
| 最小可行版本 | ✅ 自动回退到前沿节点 + 跨轮持久 graph，可作为核心贡献 |
| 最大风险 | LLM 对环境突变的适应能力未知 |
