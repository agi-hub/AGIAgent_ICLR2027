# abl21: Experience 检索消融实验（修复版）

> 模型: GLM-5.2 | 条件: w/ (Experience, World Model), w/o (Knowledge, HardProtect) | 游戏数: 6 | 迭代: 10 | 步数: 110 | 并行度: 6
>
> 实验: abl21_glm52_no_knowledge | 日期: 2026-08-19
>
> 耗时: ~8.3 小时 | API 状态: 0 次真实 429 限流错误（数据干净）

---

## 1. 实验背景与修复内容

### 1.1 旧实验（abl19_glm52_no_knowledge）的缺陷

旧实验中 play prompt 写死了 `section="knowledge"` 查询，在 no_knowledge 消融下：
- Agent 发出的 77 次 wiki_memory_read 全部 `section='knowledge'`，全部撞墙返回 "knowledge disabled by ablation"
- Agent 从未尝试查 `experiences`（prompt 未告知该 section 存在）
- **Experience 组件实际未被使用**——旧结果 162.9 avg 基本等于 WM-only (180.1) 减噪声

### 1.2 修复内容

修改 `apps/tale_jericho/run_all_tasks.py` 的 `_play_requirement()`：当 ablation 为 `no_knowledge` 时，注入专门的 STRATEGY 提示：

```
Prior playthrough EXPERIENCES from earlier attempts ARE available.
STRATEGY: Query the wiki for past attempt records (section="experiences").
They summarize what worked, what killed the agent, and what was discovered in each earlier attempt.
```

验证：`section="experiences"` 在 no_knowledge ablation 下正常返回 experience 内容（smoke test 通过）。

---

## 2. 逐游戏逐迭代得分

| Game | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | best | avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Detective | 360 | 30 | 330 | 350 | 350 | 350 | 350 | 350 | 190 | 80 | 350 | 350 | 273.0 |
| Library | 30 | 6 | 10 | 20 | 15 | 20 | 8 | 20 | 20 | 21 | 20 | 21 | 16.0 |
| Zork1 | 350 | 55 | 59 | 74 | 59 | 59 | 69 | 79 | 83 | 0 | 54 | 83 | 59.1 |
| Zork3 | 7 | 0 | 3 | 5 | 4 | 5 | 5 | 5 | 6 | 6 | 0 | 6 | 3.9 |
| Balances | 51 | 5 | 20 | 5 | 15 | 15 | 15 | 15 | 10 | 20 | 20 | 20 | 14.0 |
| Temple | 35 | 8 | 13 | 13 | 13 | 13 | 13 | 13 | 13 | 18 | 18 | 18 | 13.5 |
| **TOTAL** | | 104 | 435 | 467 | 446 | 462 | 450 | 477 | 322 | 145 | 432 | **498** | **379.5** |

---

## 3. 五条件完整对比（更新版）

| Game | max | full | **w/ (Exp, WM)**<br>**w/o (Know, HP)** | w/ WM<br>w/o (Know, Exp, HP) | Naive ReAct |
|---|---|---|---|---|---|
| Detective | 360 | 297.0 | **273.0** | 80.0 | 60.0 |
| Library | 30 | **29.1** | 16.0 | 21.1 | 22.6 |
| Zork1 | 350 | 61.6 | **59.1** | 53.1 | 45.6 |
| Zork3 | 7 | 3.6 | **3.9** | 3.0 | 3.4 |
| Balances | 51 | **19.5** | 14.0 | 14.5 | 14.0 |
| Temple | 35 | **22.0** | 13.5 | 8.4 | 7.1 |
| **TOTAL avg** | | **432.8** | **379.5** | **180.1** | **152.7** |
| **Δ vs Naive ReAct** | | +280.1 (+183%) | **+226.8 (+148%)** | +27.4 (+18%) | 基线 |

---

## 4. 关键发现

1. **Experience 检索修复后价值暴涨**：从旧实验的 162.9 → 379.5（+133%），接近 full 的 432.8（仅差 12%）。
2. **Detective 上 Experience 几乎追平 knowledge**：273.0 vs full 的 297.0。原因：curator 每轮在 experience 里写入详细的得分路径和死亡陷阱（"Key finding" 包含完整路线），experience 文件本身承载了 knowledge 的大部分有效信息。
3. **Knowledge 的增量价值主要在 Library/Balances/Temple**：这三个游戏 full 明显高于 Experience-only（29.1 vs 16.0, 19.5 vs 14.0, 22.0 vs 13.5）。压缩后的 knowledge 更精炼、可执行性更强，而未压缩的 experience 在需要精确多步序列的游戏上信噪比不足。
4. **组件贡献重排**（vs Naive ReAct）：
   - Experience + WM: +226.8（占总增益 81%）
   - Knowledge + FATAL 的增量（full 减去 Exp+WM）: +53.3（占 19%）
5. **旧消融结论作废**：ablation.md 中 "Experience 检索无价值（-6.1%）" 的结论基于 prompt 缺陷，不成立。

---

## 5. 对 ablation.md 的修订说明

本实验（abl21）取代 abl19_glm52_no_knowledge 作为 "w/ (Exp, WM), w/o (Know, HP)" 条件的有效数据。ablation.md 中的以下内容需要更新：

- 第 1.2 节得分表（旧 162.9 → 新 379.5）
- 第 2 节四条件对比表
- 第 3.3 节 "Experience 单独贡献" 分析（原结论已失效）
- 第 3.4 节组件贡献排序

旧数据（abl19_glm52_no_knowledge）保留在原处作对照，标记为 "prompt 缺陷版"。
