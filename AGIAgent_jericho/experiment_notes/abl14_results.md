# abl14 实验结果：Wiki-Evolve 系统改进效果验证

> 模型: GLM-4.7 | 游戏数: 9 | 迭代: 10 | 每迭代步数: 100 | 并行度: 3+3
>
> 日期: 2026-07-25

---

## 1. 实验配置

### 1.1 本轮改动（相对于 abl11）

abl14 相对 abl11（上一轮 GLM-4.7 full 实验）做了以下系统性改进：

| 改动 | 说明 |
|---|---|
| **wiki_memory_read 返回完整内容** | 不再截断到 200 字符，返回完整 knowledge 文件内容。abl11 时 54% 的 agent 因截断被迫自行 `cat` 全文 |
| **max_results 强制 cap=3** | 不管大模型传 5/10/100，最多返回 3 个匹配 |
| **Loop 检测修复** | 从纯 action 文本匹配改为 `(action, room)` 对匹配。abl11 时虚报率 ~100%（308 触发中 47/47 随机样本为虚报），修复后虚报降至 0%（308→4 触发） |
| **Loop hint 带未试命令** | 触发时从 admissible_commands 中计算未试动作，直接给出可操作建议 |
| **query_wm 工具** | 新增世界模型图查询工具，内存维护房间-动作-连接图，大模型可查看已探索地图和未试动作 |
| **knowledge→experience 链接** | knowledge 文件每条事实标注 Evidence 链接到来源 experience 文件 |
| **每迭代步数 200→100** | 根据 abl12 轮次-得分分析，100 轮覆盖 91-95% 的 200 轮总分，成本减半 |

### 1.2 实验条件

| 条件 | 配置 |
|---|---|
| **full** | 完整 Wiki-Evolve: knowledge + experiences + FATAL 拦截 + loop 检测 + wiki_memory_read + query_wm |
| **no_wiki** | 无 wiki 知识、无 query_wm、无 FATAL 拦截；保留 loop 检测 |

---

## 2. 逐游戏逐迭代得分

### abl14_glm_full

| Game | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | best | avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Detective | 360 | 120 | 130 | 320 | 90 | 200 | 310 | 320 | 300 | 30 | 300 | 320 | 212.0 |
| Library | 30 | 21 | 21 | 28 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 28.0 |
| Zork1 | 350 | 54 | 45 | 45 | 59 | 45 | 50 | 45 | 59 | 50 | 64 | 64 | 51.6 |
| Zork3 | 7 | 3 | 3 | 3 | 3 | 5 | 3 | 4 | 3 | 3 | 3 | 5 | 3.3 |
| Balances | 51 | 10 | 10 | 10 | 10 | 10 | 5 | 10 | 10 | 10 | 10 | 10 | 9.5 |
| Temple | 35 | 5 | 8 | 15 | 15 | 15 | 13 | 13 | 15 | 12 | 15 | 15 | 12.6 |
| Deephome | 300 | 1 | 26 | 26 | 31 | 68 | 40 | 58 | 109 | 63 | 108 | 109 | 53.0 |
| Adventureland | 100 | 0 | 14 | 14 | 0 | 0 | 21 | 14 | 21 | 21 | 7 | 21 | 11.2 |
| Murdac | 250 | 0 | 0 | 13 | 0 | 16 | 27 | 0 | 0 | 10 | 0 | 27 | 6.6 |
| **TOTAL** | | 214 | 257 | 474 | 238 | 389 | 499 | 494 | 547 | 229 | 537 | **601** | **387.8** |

### abl14_glm_no_wiki

| Game | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | best | avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Detective | 360 | 30 | 120 | 20 | 20 | 130 | 30 | 90 | 110 | 120 | 20 | 130 | 69.0 |
| Library | 30 | 20 | 21 | 21 | 20 | 20 | 21 | 29 | 21 | 19 | 13 | 29 | 20.5 |
| Zork1 | 350 | 35 | 29 | 50 | 45 | 30 | 55 | 59 | 25 | 55 | 55 | 59 | 43.8 |
| Zork3 | 7 | 3 | 3 | 1 | 0 | 2 | 1 | 4 | 1 | 3 | 2 | 4 | 2.0 |
| Balances | 51 | 15 | 10 | 15 | 15 | 15 | 15 | 10 | 15 | 10 | 15 | 15 | 13.5 |
| Temple | 35 | 20 | 10 | 15 | 22 | 12 | 10 | 15 | 20 | 15 | 12 | 22 | 15.1 |
| Deephome | 300 | 27 | 1 | 1 | 1 | 25 | 1 | 15 | 1 | 28 | 66 | 66 | 16.6 |
| Adventureland | 100 | 21 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 21 | 2.8 |
| Murdac | 250 | 0 | 0 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 0 | 14 | 1.4 |
| **TOTAL** | | 171 | 194 | 123 | 123 | 234 | 154 | 222 | 193 | 250 | 183 | **360** | **184.7** |

---

## 3. full vs no_wiki 对比

| Game | max | full avg | no_wiki avg | Δ avg | full best | no_wiki best | Δ best |
|---|---|---|---|---|---|---|---|
| Detective | 360 | 212.0 | 69.0 | **+143.0** | 320 | 130 | +190 |
| Library | 30 | 28.0 | 20.5 | +7.5 | 30 | 29 | +1 |
| Zork1 | 350 | 51.6 | 43.8 | +7.8 | 64 | 59 | +5 |
| Zork3 | 7 | 3.3 | 2.0 | +1.3 | 5 | 4 | +1 |
| Balances | 51 | 9.5 | 13.5 | **-4.0** | 10 | 15 | -5 |
| Temple | 35 | 12.6 | 15.1 | **-2.5** | 15 | 22 | -7 |
| Deephome | 300 | 53.0 | 16.6 | **+36.4** | 109 | 66 | +43 |
| Adventureland | 100 | 11.2 | 2.8 | +8.4 | 21 | 21 | +0 |
| Murdac | 250 | 6.6 | 1.4 | +5.2 | 27 | 14 | +13 |
| **TOTAL** | | **387.8** | **184.7** | **+203.1 (+110%)** | **601** | **360** | **+241** |

---

## 4. 与历史实验对比

### 4.1 GLM-4.7 full 条件跨轮次演进

| 指标 | abl8 (6游戏) | abl9 (6游戏) | abl11 (9游戏,200轮) | abl14 (9游戏,100轮) |
|---|---|---|---|---|
| best 总和 | 409 | 456 | 587 | **601** |
| avg 总和 | 152.6 | 212.4 | 267.6 | **387.8** |
| 步数/迭代 | 200 | 200 | 200 | 100 |

### 4.2 Detective 单游戏 avg 演进

| abl8 | abl9 | abl11 | abl14 |
|---|---|---|---|
| 119.0 | 126.0 | 92.0 | **212.0** |

Detective avg 从 abl11 的 92.0 跃升至 212.0 (+130%)。原因：完整 knowledge 返回（不再截断）让 agent 拿到完整的 24 步 scoring path。

### 4.3 full vs no_wiki 增益扩大

| 轮次 | full avg | no_wiki avg | Δ | 增益率 |
|---|---|---|---|---|
| abl11 (200轮) | 267.6 | 140.0 | +127.6 | +91% |
| abl14 (100轮) | 387.8 | 184.7 | +203.1 | **+110%** |

100 轮 + 系统改进 > 200 轮旧系统。步数减半，avg 总和 +45%，增益率从 +91% 扩大到 +110%。

---

## 5. Balances 和 Temple 倒挂分析

7/9 游戏 full 优于 no_wiki，但 Balances (-4.0) 和 Temple (-2.5) 倒挂。经轨迹分析，两例均印证"探索坍缩"现象。

### 5.1 Balances（full 9.5 vs no_wiki 13.5）

Balances 有 3 个隐藏得分点（各 +5）：
- `examine furniture`（Ramshackle Hut 起始房间）
- `examine oats`（Pocket Valley）
- `take cube`（Inside Cave / Edge of Chasm）

**full agent 的 knowledge 从第一个 attempt 起就只记录了后两个**，从未发现 `examine furniture`。后续所有迭代的 knowledge 都不含它。Agent 拿到 knowledge 后直接奔 Pocket Valley，从不在起始房间搜索家具。

- full: `examine furniture` 尝试 **0/10 次**，得分卡在 10
- no_wiki: `examine furniture` 发现 **8/9 次**，得分达到 15

### 5.2 Temple（full 12.6 vs no_wiki 15.1）

Temple 的 knowledge 中有一条 FATAL 标记 `[FATAL:examine writing]`，但 "examine writing" 同时是核心得分动作（+5）。no_wiki agent 在后期重新触发 "examine writing"（额外 +5/+5），而 full agent 因知识锚定不敢重复执行或探索新得分点（如 `examine paper` +5）。

### 5.3 共同模式

两个倒挂案例都是**缓存式知识把 agent 锚定在已知路径上**，抑制了对未知区域的探索。knowledge 中未记录的得分点，full agent 几乎不可能发现——这验证了探索坍缩的存在，也是后续 FRAME 方向（保留前沿、按需回退探索）的现实动机。

---

## 6. query_wm 工具使用统计

| 游戏 | full 调用次数 | no_wiki 调用次数 |
|---|---|---|
| Detective | 2 | 2 |
| Library | 0 | 3 |
| Zork1 | 5 | 3 |
| Zork3 | 14 | 6 |
| Balances | 6 | 2 |
| Temple | 2 | 4 |
| Deephome | 2 | 2 |
| Adventureland | 7 | 3 |
| Murdac | 2 | 0 |
| **TOTAL** | **40** | **25** |

full 条件下 Zork3 最多（14 次）——迷宫导航需求最高。Library 最少（0 次）——线性谜题不需要地图。调用集中在探索密集的游戏（Zork3 迷宫、Zork1 大地图、Adventureland），线性游戏不调用——行为合理。

no_wiki 条件下的 25 次调用全部返回 disabled 消息（agent 尝试使用但被 ablation 拦截），说明 agent 在两种条件下都倾向于查询世界模型图，但仅 full 条件下能获取实际内容。

---

## 7. Loop Detection 统计

### 7.1 虚报修复效果

| 指标 | abl11（旧逻辑, action-only） | abl14（新逻辑, action@room） |
|---|---|---|
| 触发总数 | ~405 | 30 |
| 虚报率 | ~100% | 0% |
| Hint 内容 | 通用 "try a different direction" | 具体未试命令 |

### 7.2 分游戏触发次数

| 游戏 | full | no_wiki |
|---|---|---|
| Detective | 0 | 0 |
| Library | 4 | 0 |
| Zork1 | 2 | 0 |
| Zork3 | 0 | 0 |
| Balances | 1 | 0 |
| Temple | 7 | 0 |
| Deephome | 0 | 0 |
| Adventureland | 6 | 6 |
| Murdac | 4 | 0 |
| **TOTAL** | **24** | **6** |

full 触发远多于 no_wiki（24 vs 6），因为 full agent 存活更久（FATAL 拦截 + knowledge 路径引导），有更多机会进入循环。Adventureland 两条件都有触发——迷宫游戏地图结构复杂，agent 在两种条件下都容易迷路。所有触发均为真循环（0% 虚报）。

---

## 8. 结论

1. **full avg 总和 387.8 vs no_wiki 184.7，+203.1 (+110%)**——knowledge 系统带来翻倍提升。
2. **7/9 游戏 full 优于 no_wiki**；Balances (-4.0) 和 Temple (-2.5) 倒挂，原因是 knowledge 锚定抑制探索。
3. **100 轮 + 系统改进全面优于 200 轮旧系统**：full avg 267.6 → 387.8 (+45%)，步数减半。
4. **Detective 增益最大**（+143 avg），Deephome 次之（+36.4 avg）。前者受益于完整 knowledge 路径，后者受益于 FATAL 拦截 + knowledge 深度引导。
5. **Balances/Temple 倒挂验证探索坍缩**：缓存式知识锚定 agent 在已知路径上，未记录得分点无法被发现。
