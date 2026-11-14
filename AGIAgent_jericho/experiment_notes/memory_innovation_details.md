# 记忆机制创新细节：结构 / 形成 / 使用三轴深挖

> 基于 2026-08 版本源码（`src/wiki_memory.py`、`src/tools/tale_jericho_tools.py`、`apps/tale_jericho/run_all_tasks.py`、`apps/tale_jericho/prompts/phase_m_prompt.txt`）、知识文件（abl19/abl21/abl22 的 score_recipe_* 与 experiences/*.md）与轨迹记录的一手证据。
>
> 本文是对 `paper_innovation_points.md`（机制总览）和 `paper_innovation_top.md`（四核心创新）的补充：聚焦**记忆结构、记忆形成、记忆使用**三个轴向上未被前两份文档覆盖的细节创新，每条附代码/数据证据与论文表述建议。

---

## 一、记忆结构轴（Memory Structure）

### 1.1 按"持久性作用域"分层，而非按内容类型分层

现有文档（top.md §2.4）将三层记忆表述为 episodic→semantic→procedural 的内容分层。深挖代码后可以发现一个更本质的设计轴：**三层实际上是三种不同的持久性/可变性作用域**：

| 层 | 目录 | 可变性 | 生命周期 | 代码证据 |
|---|---|---|---|---|
| 情景层 | `experiences/YYYY-MM-DD/` | **append-only，永不改写** | 永久，单调增长 | phase_m_prompt.txt L54-56: "If the file exists, read it then append your new entry. Keep ALL previous entries." |
| 语义层 | `knowledge/score_recipe_*.md` | **每轮全量重写** | 永久，但内容每轮重构 | phase_m_prompt.txt L6: "Rewrite the knowledge file from scratch each time" |
| 工作层 | WM graph（内存 dict） | 每步更新 | **单局作用域，随 episode 重置** | tale_jericho_tools.py `_wm_graph` 在 session 生命周期内维护，不落盘进 wiki |

**创新点表述**：这是 Complementary Learning Systems（McClelland 等的快慢互补学习系统）的一个非平凡计算实例——但分层的判据不是"内容类型"而是**写入策略与持久作用域**：不可变证据层（审计基准）+ 高频重构压缩层（当前最优摘要）+ 会话级工作层（在线建图）。关键性质：**语义层是证据层的"物化视图"**——由于每次从全量证据重写（见 2.2），knowledge 理论上可以从 experiences 完全重建，知识库天然具有一致性保证与可审计性。

**与现有工作划界**：MemGPT 的分层（core/archival）是按**容量**分层且都可变；SAMem/JitRL 的记忆是单一可变平面表；Voyager 技能库只增不重写（append-only 但没有压缩视图层）。没有任何一个同时具备"不可变证据层 + 重构压缩层"的双层结构。

### 1.2 证据链接的溯源结构（Evidence-Linked Provenance）

每条 knowledge 条目强制携带指向原始情景记录的超链接（phase_m_prompt.txt L43-52），实测知识文件中每一条都合规：

```
- (Music Store→north) use pistol on dazed man first, then search — +10.
  Evidence: [Attempt 3](../experiences/2026-08-01/detective.md)
```

多轮验证的条目累积多个链接：`Evidence: [Attempt 2](...), [Attempt 10](...)`——**同一字段同时充当（a）溯源指针（b）验证计数（c）检索锚点**（链接路径含日期，构成时间线索引）。

**创新点表述**：记忆条目不是自由文本而是**带引用的断言**（claim with citation）。这带来三个可检验性质：审计性（任何 distilled 结论可回溯到产生它的原始轨迹段）、可证伪性（experience 中的原始记录若与 knowledge 矛盾，可精确定位是哪次蒸馏引入的错误）、验证度量化（Evidence 链接数 = 独立复现次数，直接被检索置信度解析器消费，见 1.4）。

**与现有工作划界**：Reflexion 的反思无来源标注；Voyager 技能无验证记录；SAMem 的 Q 值是聚合量，丢失了"哪些经历支撑这个值"。Evidence 链接是 Agent 记忆文献中少见的**数据级 provenance** 实现。

### 1.3 检索单元 = 位置索引的完整条件化策略

知识文件不是事实片段的集合，而是**按房间索引的完整有序策略**。实测 abl19 detective 知识文件：24 个步骤每条形如 `(Room) action — +Δ`，并显式标注顺序依赖（"HALLWAY MAZE (from score 200): west, north, west, north"）、种子条件（"seed-dependent: sometimes directly to Holiday Inn"）、效率变体（"310 in ~44 moves: base path only" vs "350: add pistol"）。

phase_m_prompt.txt L13-15 给出设计原因："the same command (e.g. north) can give +10 in one room and cause death in another"——所以**位置是一等公民**，且 L35 进一步规定"(Room) must be the room where the agent EXECUTES the action, not the room it leads to"（消歧：死亡拦截器依赖的是执行房间）。

**创新点表述**：这构成一个**混合神经-符号检索结构**：外层用 embedding 语义检索定位到页面（neural），页面内部 agent 按 `(Room, action)` 做符号匹配（symbolic）。检索的粒度被刻意设计为"完整策略"而非"相关片段"，因为**部分动作序列比没有序列更危险**（走到序列中段会死）。

**证据**：这是从失败设计中学到的——早期版本返回 200 字符片段，agent 大量用 shell `cat` 绕过截断读全文（实测截断版 abl8_full 11/16 plays 69% 干脆直接 cat 知识文件；abl7_full 23/83 = 28%；改为全文返回后 abl11_glm_full 降到 4/74 = 5%），证明完整策略文件才是真正的使用单元，于是改为全文返回（wiki_memory_read 现直接返回 `full_content`）。

### 1.4 内容信号置信度 × 分层检索阈值

`src/wiki_memory.py:574-640` 的排序公式：

```
final_score = cos(query, page) × confidence(page) × cross_game_penalty
```

其中 `confidence` 由 `_parse_confidence`（L166-198）从**页面内容标记**解析：Confirmed-In 计数 ≥3 → 1.0；=1 → 0.95；"verified"+"score" → 0.9；"unverified"/"risky" → 0.7；诚实失败（"scored 0"/"no score"）→ 0.6；默认 0.8。

且检索阈值**按记忆类型分化**（L579-592）：

| section | 阈值 | 设计意图 |
|---|---|---|
| knowledge | 0.30 | 精度优先——动作序列必须强相关 |
| experiences | 0.20 | 召回优先——类比教训允许宽松匹配 |
| world_model | 0.25 | 居中——导航参考 |

**创新点表述**：**记忆类型感知的 precision-recall 权衡**。不同记忆层的使用风险结构不同：错误的动作序列（knowledge）会直接致死，所以收紧；经验教训（experiences）只作参考不会被执行，所以放宽。置信度来自策展阶段写入的验证标记（1.2 的 Evidence 链接），形成"验证→置信度→检索排序"的完整闭环——**验证历史直接影响未来的检索可见性**。

**与现有工作划界**：SAMem 用连续 Q 值排序但 Q 来自 Bellman 更新（值估计）而非验证计数；标准 RAG 无置信度维度。将"离散验证状态"编译进检索排序是新的。

---

**论断**：对强模型，干预式探索启发式（MAP-FIRST 深度优先、循环警告）净贡献为负；同预算下**投资在记忆系统上回报高于投资在行为提示词上**。这为"把学习放进知识层而非 prompt 层"（对照 EvoTest 演化 prompt 配置）提供了直接证据。（数据核实：abl22 Library 逐局 3,21,21,21,20,21,130,27,21,29 avg 31.4；abl19 no_wiki 21,30,21,21,21,21,30,19,21,21 avg 22.6 best 30。）

### 2.1 确定性抽取 × LLM 合成的双阶段策展（反幻觉信任边界）

`run_all_tasks.py:469-566` 的 `_pre_extract_score_actions`：程序确定性解析 trajectory.jsonl，提取**每个分数增量动作及其房间上下文**（正则 `<<\s*(.+?)\s*>>` 从观察首行抽房间名）、死亡事件（done ∧ ¬won），生成结构化摘要注入 Curator prompt，并明确指示：

```
"Pre-Extracted Trajectory Summary (auto-generated — do NOT re-parse the trajectory file)"
"Use the above as your primary data source... Focus your effort on SYNTHESIZING knowledge (connecting fragments), not parsing."
```

实测效果（abl19 detective phasem 轨迹）：早期版本 Curator 要花 3+ 轮 shell 调用解析 trajectory.jsonl（`python3 -c "import json..."` 逐行打印）；修复后直接消费预提取摘要。

**创新点表述**：策展被分解为**信任边界分明的两个通道**：数值事实（分数增量、动作、房间、死亡）由代码提取，**从不经过 LLM 之手**——LLM 幻觉无法伪造"+10"；LLM 只负责它擅长的**跨条目合成**（把碎片拼成策略、推断顺序、识别矛盾）。这是"LLM as synthesizer, not transcriber"的原则性设计。Reflexion/EvoTest 中 LLM 直接阅读原始轨迹回忆发生了什么，数值细节（分数增量多少）完全依赖 LLM 的忠实转述。

**与现有工作划界**：EvoTest 的 Evolver 读原始输出自行总结；GLoW 的值分解也依赖 LLM 读轨迹。据我们所知，"程序化预提取 + 禁止 LLM 重解析"的策展分工在测试时学习 Agent 文献中未见先例。

### 2.2 Rewrite-from-scratch：生成式重压缩代替冲突消解

phase_m_prompt.txt L6："Rewrite the knowledge file from scratch each time, merging old + new knowledge. Target under 800 words."

传统增量知识库需要显式冲突消解逻辑（检测旧新条目矛盾 → 保留谁）。本方案绕开了整个问题：**每轮基于全部证据（旧 knowledge + 全部 experiences + 新轨迹摘要）重新生成**，冲突在生成时自然消解——错误条目不被"修正"而是不被重新写出（天然遗忘），验证充分的条目被反复写出（Evidence 链接累积）。

**创新点表述**：这是记忆研究中**重构主义观点（reconstruction over replication）**的工程化：回忆不是回放存储内容，而是基于证据的重新生成。带来的三个可证明性质：（a）知识库大小有界（≤800 words，防膨胀——对照 Voyager 技能库单调膨胀）；（b）无冲突累积（没有"最新修正覆盖在哪条后面"的查找问题）；（c）**新颖性偏置**：每轮重写天然偏向"当前最优压缩"，过时路线自动淘汰。代价（诚实披露）：重写依赖 Curator 质量，一旦某轮写得差，下轮可能丢信息——但 Evidence 链接的原始 experiences 层永远可回溯补救（见 1.1 的物化视图性质）。

### 2.3 负向知识的单独编码与安全阀规则（FATAL 语法）

知识库不只存"怎么做"，还存**"什么会杀死你"**，且有专门的语法与三条安全阀（phase_m_prompt.txt L32-35 + tale_jericho_tools.py:639-762 的解析器）：

1. **"Only mark [FATAL] on actions that NEVER score"**——有时得分有时致死的动作（条件性死亡）必须放入 Unexplored 而非 Death Traps。解析器同构实现（L666-671）：收集所有得分行文本，FATAL 关键词若出现在任何得分行中则跳过不拦截。
2. **房间 = 执行房间**——L35 显式消歧，拦截器按当前房间匹配（词级重叠 ≥3 字符，L751）。
3. **导航词 + 未知房间 → 跳过拦截**（L754-758）——防止过度封锁探索。

**创新点表述**：**负向经验（death traps）作为一等知识类型**，带防误伤规则集，且从"语义标记"被**编译为运行时约束**（见 3.1）。RL 文献中死亡惩罚只是标量信号；这里死亡被编码为可检索、可定位（房间条件化）、可执行的禁令。三条安全阀本身是消融驱动的（abl17 曾因 "Bar" 房间 `len>3` 阈值匹配失败、过度封锁导航而翻车，修复后 Detective 297）。

### 2.4 情景层的自发半蒸馏现象（abl21 意外发现）

abl21（no_knowledge：agent 只能查 experiences）达到 379.5 = full 的 88%。检查 abl21 的 experience 文件发现原因：Curator 写 experience 的 "Key finding" 字段实际上**包含了完整得分路线和死亡陷阱**——例如 detective experience Attempt 2 的 Key finding 是一整条从 Chief's office 到 Room #30 的完整路线图。

**创新点表述（实证性论断）**：**策展人在写"原始记录"时自发进行了蒸馏**——情景层的写入格式（结构化的 Route/Death traps/Remaining 字段）使其携带了语义层的多数信息。这揭示了一个重要机制事实：本框架的性能不依赖"哪一层被检索"（experiences 与 knowledge 内容高度重叠），而主要依赖**"是否有策展这个环节"**。蒸馏（knowledge 层）的边际价值集中在需要精确多步序列的游戏（见 4.1）。这个发现同时是警告：**消融实验必须验证每层真的被隔离了**（abl19 no_knowledge 曾因 prompt 路由 bug 全部失效，162.9 的"消融结果"实际测的是 WM-only）。

---

## 三、记忆使用轴（Memory Usage）

### 3.1 记忆→动作空间编译（Memory-to-Action-Space Compilation）

`_check_fatal_action`（tale_jericho_tools.py:639-762）：知识文件中的 `[FATAL:action] (Room)` 条目在**工具执行层**被解析（按 mtime 缓存），匹配的动作在发送给环境**之前**被硬拦截：

```
BLOCKED: 'search dazed man' is marked [FATAL] in knowledge. Choose a different action.
```

**创新点表述**：这是记忆使用方式上与现有工作最大的分化点——检索到的知识不只进入 prompt（软影响），而是**改写 agent 的可行动作集合**（硬约束）。形成完整闭环：策展产出语义标记（FATAL）→ 标记被编译为运行时策略 → 拦截结果出现在下一轮策展的轨迹里（"BLOCKED" 事件），构成记忆的自我执行与自我验证循环。消融证据：去掉 FATAL 拦截（其余 full 配置不变），Detective 297→165（-44%）。

**与现有工作划界**：MemGPT 的记忆管理是上下文内的分页；Voyager 的技能是主动调用；没有任何 Agent 记忆系统把记忆条目编译成环境交互前的硬约束。最接近的类比是 shielded RL / safe action masking，但那依赖预定义的安全函数，而这里的约束是**agent 自己从死亡经历中策展出来的**（self-curated shield）。

### 3.2 预算化拉取（3 次/局）+ 单次推送的双通道访问

- **Pull 通道**：`wiki_memory_read` 每局限 3 次查询（wiki_memory.py:418, 446-453），超限返回"Rely on wiki_hint"。强迫 agent 做**注意力分配决策**（何时值得查记忆），防止上下文被检索结果饱和。
- **Push 通道**（可选）：`_auto_wiki_hint`（tale_jericho_tools.py:524+）在**首次分数变化时**注入一次完整知识 recipe，之后不再注入——"第一次得分证明 agent 在正确的轨道上，此刻注入完整路径收益最大"的触发设计。

**创新点表述**：记忆访问的**稀疏性是设计目标而非缺陷**。与"每步检索 top-k 注入上下文"的标准 RAG-agent 范式（AWM、SAMem 均如此）相反，本方案的记忆访问是事件驱动、预算约束的。3 次预算实测够用（每次返回完整 recipe 全文，见 1.3）。

### 3.3 分层查询路由是系统的一部分（prompt-level section routing）

Play prompt 显式告知 agent 查哪个 section（"STRATEGY: Query the wiki for score-increasing actions (section=\"knowledge\")..."），且**路由逻辑是消融感知的**（run_all_tasks.py:400-418：no_knowledge 时改写为 `section="experiences"`）。

**教训即证据**：abl19 的 no_knowledge 消融因 prompt 硬编码 `section="knowledge"` 而完全失效（77 次查询全部撞"knowledge disabled"墙，agent 从未被告知可查 experiences），162.9 的结果实际测的是 WM-only；abl21 修复路由后同条件得 379.5（+133%）。**记忆使用方式的说明本身是记忆系统语义的一部分**——错一层路由等于整个记忆层失效。这个 bug→修复的对照是"记忆系统的接口设计与记忆内容同等重要"的天然实验证据。

### 3.4 Episode 内工作记忆：frontier 计算 + 可行动的循环提示

WM graph（tale_jericho_tools.py:153-272）维护每房间的 tried_actions / admissible_seen / visits，计算 **frontier = admissible_seen − tried**（有未试动作的房间），`query_wm` 返回文本化图 + frontier 标记，供 agent 决定"哪里还有没试的"。循环检测用 `(action, room)` 对（不是纯 action——纯 action 误报率曾 100%），触发时**从 admissible_commands 里挑未试命令给出可行动建议**而非泛泛警告。

**创新点表述**：工作记忆的**未试动作集合（frontier）显式计算并暴露给 agent**，把"探索哪里"从隐式 LLM 判断变成显式集合差运算。这层刻意不持久化（每局重置），与 1.1 的分层互为印证——地图是 episode 特定的，持久化它反而引入过时信息。

---

## 四、新证据支撑的论文级论断（abl21/abl22 数据）

### 4.1 蒸馏的边际价值是任务结构依赖的

| Game | full | Exp-only (abl21) | knowledge 增量 | 游戏特征 |
|---|---|---|---|---|
| Detective | 297.0 | 273.0 | +24.0 (9%) | 线性路线，宽容 |
| Zork1 | 61.6 | 59.1 | +2.5 (4%) | 开放探索 |
| Library | 29.1 | 16.0 | **+13.1 (+82%)** | 精确多步序列（give X before Y） |
| Temple | 22.0 | 13.5 | **+8.5 (+63%)** | 精确咒语序列 |
| Balances | 19.5 | 14.0 | +5.5 (+39%) | 顺序敏感的施法 |
| TOTAL | 432.8 | 379.5 | +53.3 (12%) | |

**论断**：未蒸馏的 experience 日志（带自发半蒸馏结构，见 2.4）即可拿到 88% 的收益；**压缩蒸馏的边际价值集中在动作顺序敏感的任务**（Library 的 "give id card BEFORE novel" 类约束在原始经验流里分散在多轮，只有重写式蒸馏才把它固化成显式 ordering 规则——实测 abl21 library experience Attempt 3 才发现 ordering，而 full 的 knowledge 从发现当轮就固化了它）。这是"何时需要记忆压缩"的首个任务维度定量刻画。

### 4.2 记忆内容 > 行为脚手架（abl22）

纯 ReAct（去 loop detection + 去探索策略提示词）178.7 **高于**带完整脚手架的 Naive ReAct 152.7（+17%）。Library 上纯 ReAct 甚至单局解出 130（脚手架版从未超过 27）。

**论断**：对强模型，干预式探索启发式（MAP-FIRST 深度优先、循环警告）净贡献为负；同预算下**投资在记忆系统上回报高于投资在行为提示词上**。这为"把学习放进知识层而非 prompt 层"（对照 EvoTest 演化 prompt 配置）提供了直接证据。

### 4.3 护栏与路径知识的冗余结构（FATAL 反事实）

知识引导路径防 9/10 死亡；FATAL 硬拦截直接拦 5/10。两者大部分重叠——**护栏的主要价值在 agent 偏离已知路径时兜底**，而非替代好的知识。这支持 3.1 的定位：编译式约束是保险机制，不是性能机制的主引擎（主引擎是 knowledge 检索），但去掉保险的代价在高风险游戏上可达 -44%。

---

## 五、论文写作建议：主张与不主张

**建议主张（有代码+消融双重证据）**：
1. 持久性作用域三层结构（1.1）+ 物化视图性质（可从证据层重建）
2. Evidence 链接的数据级溯源（1.2）
3. 确定性抽取×LLM 合成的策展信任边界（2.1）
4. Rewrite-from-scratch 生成式重压缩（2.2）
5. 负向知识编码 + 记忆→动作空间编译（2.3+3.1，消融 -44%）
6. 验证历史编译进检索排序的闭环（1.4）
7. 任务结构依赖的蒸馏边际价值（4.1）
8. 记忆内容 > 行为脚手架（4.2）

**诚实归属既有技术（不要主张）**：
- embedding 检索本身（标准 RAG）
- applies_to 软跨游戏过滤（工程调参，α=0.3）
- 循环检测、admissible_commands 利用（Jericho 基建）
- 环境 reward 作验证信号（JitRL/SAMem/EvoTest/GLoW 共有）

**可补充的实验（增强上述主张）**：
- 1.1 物化视图性质：删掉 knowledge 目录只留 experiences，跑一轮 Curator 看重建质量（验证"可完全重建"）
- 2.1 信任边界：让 Curator 不用预提取摘要自己读原始轨迹，对比知识中分数增量字段错误率
- 1.4 置信度闭环：关掉 confidence 乘子（恒 1.0），对比检索命中与最终分
