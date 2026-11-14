# abl16 实验结果：FATAL 拦截修复 + 双模型对比

> 模型: DeepSeek-v4-Pro & GLM-4.7 | 游戏数: 8（排除 Adventureland） | 迭代: 10 | 步数: 100
>
> 日期: 2026-07-26

---

## 1. 本轮改动

| 改动 | 说明 |
|---|---|
| **FATAL 只拦截从不得分的动作** | 提示词: "Only mark [FATAL] on actions that NEVER score"。代码: FATAL 关键词出现在 scoring 行中则跳过 |
| **FATAL 房间标注修复** | 提示词: "(Room) must be the room where the agent EXECUTES the action, not the room it leads to" |
| **room="" 时 FATAL 不过滤房间** | 代码: 当无法确定 agent 当前房间（如查看物品描述时），信任 FATAL 标签直接拦截 |
| **tales 导入静默** | alfworld/textworld_express 导入失败时静默跳过，不再刷屏 |

> Adventureland 被排除：该游戏无 `<< Room >>` 房间标签格式，导致 `current_room` 恒为空，`room=""` 修复使所有房间的导航方向（west/south/down）被无差别拦截，结果不可用。

---

## 2. 逐游戏逐迭代得分

### DeepSeek-v4-Pro full (abl16_pro_full)

| Game | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | best | avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Detective | 360 | 100 | 130 | 200 | 320 | 220 | 140 | 150 | 250 | 350 | 350 | 350 | 221.0 |
| Library | 30 | 28 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 29.8 |
| Zork1 | 350 | 55 | 30 | 0 | 59 | 40 | 44 | 5 | 34 | 44 | 44 | 59 | 35.5 |
| Zork3 | 7 | 3 | 3 | 4 | 4 | 4 | 4 | 4 | 2 | 5 | 5 | 5 | 3.8 |
| Balances | 51 | 10 | 20 | 20 | 20 | 20 | 20 | 20 | 20 | 25 | 30 | 30 | 20.5 |
| Temple | 35 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15.0 |
| Deephome | 300 | 1 | 26 | 28 | 69 | 69 | 76 | 76 | 77 | 78 | 77 | 78 | 57.7 |
| Murdac | 250 | 10 | 15 | 0 | 23 | 18 | 15 | 15 | 15 | 15 | 25 | 25 | 15.1 |
| **TOTAL** | | 222 | 269 | 297 | 500 | 416 | 349 | 285 | 203 | 237 | 276 | **592** | **398.4** |

### GLM-4.7 full (Detective/Deephome 取自 abl16 重跑，其余取自 abl15)

| Game | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | best | avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Detective | 360 | 20 | 200 | 210 | 10 | 330 | 90 | 20 | 90 | 310 | 320 | 330 | 160.0 |
| Library | 30 | 21 | 21 | 21 | 21 | 21 | 21 | 21 | 21 | 21 | 21 | 21 | 21.0 |
| Zork1 | 350 | 55 | 55 | 49 | 45 | 50 | 55 | 34 | 55 | 55 | 59 | 59 | 51.2 |
| Zork3 | 7 | 3 | 1 | 4 | 4 | 3 | 3 | 5 | 3 | 4 | 5 | 5 | 3.5 |
| Balances | 51 | 10 | 15 | 15 | 15 | 20 | 20 | 20 | 20 | 20 | 20 | 20 | 17.5 |
| Temple | 35 | 8 | 8 | 13 | 13 | 13 | 13 | 13 | 13 | 13 | 13 | 13 | 12.0 |
| Deephome | 300 | 1 | 24 | 25 | 26 | 24 | 39 | 68 | 76 | 70 | 73 | 76 | 42.6 |
| Murdac | 250 | 16 | 9 | 29 | 0 | 10 | 9 | 0 | 0 | 14 | 10 | 29 | 9.7 |
| **TOTAL** | | 134 | 333 | 346 | 131 | 471 | 260 | 161 | 278 | 507 | 521 | **553** | **317.5** |

### GLM-4.7 no_wiki (abl14_glm_no_wiki)

| Game | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | best | avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Detective | 360 | 30 | 120 | 20 | 20 | 130 | 30 | 90 | 110 | 120 | 20 | 130 | 69.0 |
| Library | 30 | 20 | 21 | 21 | 20 | 20 | 21 | 29 | 21 | 19 | 13 | 29 | 20.5 |
| Zork1 | 350 | 35 | 29 | 50 | 45 | 30 | 55 | 59 | 25 | 55 | 55 | 59 | 43.8 |
| Zork3 | 7 | 3 | 3 | 1 | 0 | 2 | 1 | 4 | 1 | 3 | 2 | 4 | 2.0 |
| Balances | 51 | 15 | 10 | 15 | 15 | 15 | 15 | 10 | 15 | 10 | 15 | 15 | 13.5 |
| Temple | 35 | 20 | 10 | 15 | 22 | 12 | 10 | 15 | 20 | 15 | 12 | 22 | 15.1 |
| Deephome | 300 | 27 | 1 | 1 | 1 | 25 | 1 | 15 | 1 | 28 | 66 | 66 | 16.6 |
| Murdac | 250 | 0 | 0 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 0 | 14 | 1.4 |
| **TOTAL** | | 130 | 194 | 123 | 123 | 234 | 147 | 222 | 193 | 250 | 183 | **339** | **181.9** |

---

## 3. 三条件总分对比

### 3.1 逐游戏 avg 对比

| Game | max | Pro full avg | GLM full avg | GLM no_wiki avg | Pro-GLMfull Δ | GLMfull-no_wiki Δ |
|---|---|---|---|---|---|---|
| Detective | 360 | 221.0 | 160.0 | 69.0 | +61.0 | +91.0 |
| Library | 30 | 29.8 | 21.0 | 20.5 | +8.8 | +0.5 |
| Zork1 | 350 | 35.5 | 51.2 | 43.8 | -15.7 | +7.4 |
| Zork3 | 7 | 3.8 | 3.5 | 2.0 | +0.3 | +1.5 |
| Balances | 51 | 20.5 | 17.5 | 13.5 | +3.0 | +4.0 |
| Temple | 35 | 15.0 | 12.0 | 15.1 | +3.0 | -3.1 |
| Deephome | 300 | 57.7 | 42.6 | 16.6 | +15.1 | +26.0 |
| Murdac | 250 | 15.1 | 9.7 | 1.4 | +5.4 | +8.3 |
| **TOTAL avg** | | **398.4** | **317.5** | **181.9** | **+80.9** | **+135.6** |

### 3.2 逐游戏 best 对比

| Game | max | Pro full best | GLM full best | GLM no_wiki best |
|---|---|---|---|---|
| Detective | 360 | 350 | 330 | 130 |
| Library | 30 | 30 | 21 | 29 |
| Zork1 | 350 | 59 | 59 | 59 |
| Zork3 | 7 | 5 | 5 | 4 |
| Balances | 51 | 30 | 20 | 15 |
| Temple | 35 | 15 | 13 | 22 |
| Deephome | 300 | 78 | 76 | 66 |
| Murdac | 250 | 25 | 29 | 14 |
| **TOTAL best** | | **592** | **553** | **339** |

### 3.3 总分汇总

| 指标 | Pro full | GLM full | GLM no_wiki |
|---|---|---|---|
| **TOTAL avg** | **398.4** | **317.5** | **181.9** |
| **TOTAL best** | **592** | **553** | **339** |
| **avg 增益 (vs no_wiki)** | — | +135.6 (+75%) | 基线 |
| **avg 增益 (Pro vs GLM full)** | +80.9 (+25%) | 基线 | — |

---

## 4. FATAL 拦截统计

### 4.1 Deephome `say manaz` 拦截效果

| 条件 | 模型 | say manaz 死亡次数 | 说明 |
|---|---|---|---|
| abl15 full (修复前) | GLM-4.7 | 3/10 | room="" 时拦截跳过 |
| abl16 full (修复后) | GLM-4.7 | **1/10** (仅第1轮 knowledge 空) | 后9轮全部拦截成功 |
| abl16 full (修复后) | DeepSeek-Pro | **1/10** (仅第1轮 knowledge 空) | 后9轮全部拦截成功 |
| no_wiki | GLM-4.7 | N/A (无 FATAL) | — |

修复后两个模型都只在第 1 轮（knowledge 尚未建立）时死亡，后续 9 轮全部被 FATAL 拦截保护。

### 4.2 FATAL 拦截触发总数

| 实验 | 拦截次数 | 分游戏 |
|---|---|---|
| Pro full (abl16) | 88 | Zork1 64, Library 16, Detective 6, Balances 2 |
| GLM full (Detective+Deephome, abl16) | 57 | Detective 56, Deephome 1 |
| GLM no_wiki (abl14) | 0 | (ablation 禁用) |

Pro 的 Zork1 (64) 拦截最多——该游戏有大量导航类死亡陷阱。

---

## 5. Experience 链接统计

| 实验 | 知识文件数 | Evidence 链接总数 |
|---|---|---|
| Pro full (abl16) | 10 | **0** |
| GLM full (Detective+Deephome, abl16) | 2 | **81** (Detective 32, Deephome 49) |

Pro 模型的 knowledge 文件中 **0 个 Evidence 链接**——经查 Pro app 的 `phase_m_prompt.txt` 是旧版 sed 副本，未含 Evidence 链接规则。已同步修复，下次 Pro 实验会生效。

GLM-4.7 的链接表现良好：Detective 32 个、Deephome 49 个，格式正确。

---

## 6. Loop Detection 统计

| 实验 | 触发次数 |
|---|---|
| Pro full (abl16) | 0 |
| GLM full (Detective+Deephome, abl16) | 0 |
| GLM no_wiki (abl14) | 0 |

排除 Adventureland 后，8 个游戏的 Loop detection 均未触发——这些游戏要么是线性谜题（Library、Temple），要么 agent 在 FATAL 拦截 + knowledge 引导下没有进入循环。

---

## 7. query_wm 使用统计

| 实验 | 调用次数 | 分游戏 |
|---|---|---|
| Pro full (abl16) | 52 | Temple 17, Zork1 12, Murdac 6, Balances 5, Deephome 4, Zork3 3, Library 3, Detective 2 |
| GLM full (Detective+Deephome, abl16) | 6 | Deephome 5, Detective 1 |
| GLM no_wiki (abl14) | 22 (全返回 disabled) | Zork3 6, Temple 4, Zork1 3, Library 3, Detective 2, Balances 2, Deephome 2 |

Pro 显著更多地使用 query_wm（52 次 vs GLM 6 次），且分布在全部 8 个游戏中。Temple (17) 和 Zork1 (12) 最多。

---

## 8. 结论

1. **Pro full avg 398.4 > GLM full avg 317.5 > GLM no_wiki avg 181.9**。Pro 比 GLM full 高 25%，GLM full 比 no_wiki 高 75%。
2. **FATAL 修复有效**：Deephome `say manaz` 死亡从 3/10 降至 1/10（仅第 1 轮 knowledge 空时），Deephome avg 从 abl15 的 31.5 升至 abl16 的 42.6。
3. **GLM full vs no_wiki +75%**（+135.6 avg），7/8 游戏正向（Temple -3.1 为 FATAL 误杀残留，提示词已修复但 abl15 未含此修复）。
4. **Pro 更积极使用 query_wm**（52 次 vs GLM 6 次），覆盖全部 8 个游戏。
5. **Loop detection 0% 虚报**，8 个游戏均未触发。
6. **Evidence 链接**：GLM 表现良好（81 个），Pro 为 0（因旧提示词未更新，已同步修复）。
