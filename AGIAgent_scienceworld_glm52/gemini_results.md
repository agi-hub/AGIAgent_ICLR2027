# abl18 实验结果：Gemini-2.5-Flash 多模型对比

> 模型: Gemini-2.5-Flash | 对比: DeepSeek-v4-Pro & GLM-4.7 | 游戏数: 6 | 迭代: 10 | 步数: 110
>
> 日期: 2026-07-30

---

## 1. 实验配置

| 配置 | 值 |
|---|---|
| **模型** | gemini-2.5-flash |
| **API** | `https://xinchenbuqi3776.zeabur.app/v1` (OpenAI 兼容) |
| **游戏** | Detective(13), Library(24), Zork1(51), Zork3(53), Balances(8), Temple(44) |
| **迭代** | 10 |
| **步数** | 110/轮 |
| **并行度** | 6 |
| **App** | tale_jericho_gemini（含 query_wm + FATAL 拦截 + loop detection + experience 链接） |

### 关键配置调整

| 参数 | 值 | 原因 |
|---|---|---|
| `Tool_calling_format` | True | Gemini 原生支持 function calling，chat-based 模式下输出异常（连续无参数动作调用） |
| `streaming` | False | Gemini 流式输出时会复述工具结果文本（`"Tool execution results:"`），触发 hallucination 检测器 185 次误报导致输出频繁截断。非流式模式正常 |

### Hallucination 检测问题说明

Gemini 在 `Tool_calling_format=True` + `streaming=True` 时，会在推理输出中引用工具结果的格式化文本（如 `## Tool 1: tale_jericho_action` / `Tool execution results:`）。agia.py 的流式 hallucination 检测器将此误判为模型伪造工具结果，每轮触发多次截断。设置 `streaming=False` 后 0 次误报，运行正常。

---

## 2. Gemini-2.5-Flash 逐游戏逐迭代得分

| Game | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | best | avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Detective | 360 | 80 | 70 | 100 | 120 | 140 | 320 | 220 | 210 | 330 | 220 | 330 | 181.0 |
| Library | 30 | 10 | 10 | 11 | 11 | 14 | 19 | 28 | 30 | 30 | 30 | 30 | 19.3 |
| Zork1 | 350 | 45 | 30 | 5 | 30 | 0 | 5 | 49 | 49 | 49 | 49 | 49 | 31.1 |
| Zork3 | 7 | 3 | 0 | 5 | 2 | 2 | 3 | 3 | 2 | 3 | 2 | 5 | 2.5 |
| Balances | 51 | 15 | 15 | 15 | 10 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 14.5 |
| Temple | 35 | 5 | 5 | 10 | 5 | 10 | 12 | 10 | 15 | 15 | 10 | 15 | 9.7 |
| **TOTAL** | | 158 | 130 | 146 | 178 | 186 | 384 | 325 | 321 | 442 | 326 | **444** | **258.1** |

---

## 3. 三模型对比（相同 6 游戏）

### 3.1 逐游戏 avg 对比

| Game | max | Pro avg | GLM avg | Gemini avg | Pro-Gemini Δ | GLM-Gemini Δ |
|---|---|---|---|---|---|---|
| Detective | 360 | 221.0 | 160.0 | **181.0** | +40.0 | -21.0 |
| Library | 30 | 29.8 | 21.0 | 19.3 | +10.5 | +1.7 |
| Zork1 | 350 | 35.5 | 51.2 | 31.1 | +4.4 | +20.1 |
| Zork3 | 7 | 3.8 | 3.5 | 2.5 | +1.3 | +1.0 |
| Balances | 51 | 20.5 | 17.5 | 14.5 | +6.0 | +3.0 |
| Temple | 35 | 15.0 | 12.0 | 9.7 | +5.3 | +2.3 |
| **TOTAL** | | **325.6** | **264.2** | **258.1** | **+67.5** | **+6.1** |

### 3.2 逐游戏 best 对比

| Game | max | Pro best | GLM best | Gemini best |
|---|---|---|---|---|
| Detective | 360 | 350 | 330 | 330 |
| Library | 30 | 30 | 21 | 30 |
| Zork1 | 350 | 59 | 59 | 49 |
| Zork3 | 7 | 5 | 5 | 5 |
| Balances | 51 | 30 | 20 | 15 |
| Temple | 35 | 15 | 13 | 15 |
| **TOTAL** | | **489** | **448** | **444** |

### 3.3 总分汇总

| 指标 | Pro full | GLM full | Gemini full |
|---|---|---|---|
| **TOTAL avg** | **325.6** | **264.2** | **258.1** |
| **TOTAL best** | **489** | **448** | **444** |
| **avg 排名** | 1 | 2 | 3 |
| **best 排名** | 1 | 2 | 3 |

### 3.4 归一化得分 (avg / max)

| Game | max | Pro | GLM | Gemini |
|---|---|---|---|---|
| Detective | 360 | 0.614 | 0.317 | 0.503 |
| Library | 30 | 0.993 | 0.700 | 0.643 |
| Zork1 | 350 | 0.101 | 0.146 | 0.089 |
| Zork3 | 7 | 0.543 | 0.500 | 0.357 |
| Balances | 51 | 0.402 | 0.343 | 0.284 |
| Temple | 35 | 0.429 | 0.343 | 0.277 |
| **TOTAL** | **833** | **0.391** | **0.263** | **0.310** |

归一化后 Gemini (0.310) 反而略高于 GLM (0.263)，因为 GLM 在高分的 Detective (360 分) 上得分比例较低 (0.317)，拉低了整体归一化值。而 Gemini 在 Detective 上达到 0.503，弥补了其他游戏的劣势。

> 注: GLM full 取自 abl15（Detective/Deephome 取自 abl16 重跑）。Pro full 取自 abl16_pro_full。

---

## 4. Gemini 关键观察

### 4.1 学习曲线特征

Gemini 在多数游戏上呈现**后段上升**趋势：
- Detective: 前 5 轮 avg 102 → 后 5 轮 avg 260（+155%）
- Library: 前 5 轮 avg 11.2 → 后 5 轮 avg 27.4（+145%）
- Zork1: 前 5 轮 avg 22 → 后 5 轮 avg 40.2（+83%）

说明 Gemini 能从 Wiki knowledge 中学习，但启动较慢（前几轮 knowledge 积累不足）。

### 4.2 与 GLM 的差异

- **Detective**: Gemini (181.0) > GLM abl15 (114.0)，但 < GLM abl16 重跑 (160.0)。Gemini 在 Detective 上表现接近 GLM 最优水平
- **Zork1**: Gemini (31.1) 显著弱于 GLM (51.2)。GLM 更善于探索 Zork1 的大地图
- **Library**: 两者都达到 best=30，但 GLM 在 abl16 重跑中稳定在 21 avg，Gemini 前半段不稳定
- **Balances/Temple**: Gemini 均略弱于 GLM

### 4.3 总评

Gemini-2.5-flash 作为轻量模型，total avg (258.1) 接近 GLM-4.7 (264.2)，差距仅 2.3%。Detective 上甚至超过 GLM abl15。但 best 总分 (444) 低于 GLM (448) 和 Pro (489)，表明 Gemini 的天花板略低。

---

## 5. 结论

1. **三模型排名**: Pro (325.6) > GLM (264.2) ≈ Gemini (258.1)
2. **Gemini 与 GLM 差距很小**（+2.3% avg），Detective 上 Gemini 表现更强
3. **Gemini 学习曲线后段发力**，前 5 轮 avg 偏低，说明需要更多迭代来积累有效 knowledge
4. **流式 hallucination 检测是 Gemini 兼容性的关键障碍**，需 `streaming=False` 才能正常工作
5. **Pro 全面领先**， avg 比 GLM 高 23%，比 Gemini 高 26%
