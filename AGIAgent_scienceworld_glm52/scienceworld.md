# Wiki-Evolve on ScienceWorld: GLM-5.2 Test Set 实验报告

> 日期：2026-08-08
> 模型：GLM-5.2 (BigModel coding API)
> 数据集：ScienceWorld test set（24 个任务，211 个 task-variation pairs）
> 框架：Wiki-Evolve（从 Jericho 迁移，含三层记忆 + Focus Guard + 世界模型图）

---

## 1. 实验配置

| 参数 | 值 |
|------|-----|
| 模型 | GLM-5.2 |
| 条件 | Full（知识 + 经验 + 世界模型 + Focus Guard） |
| 最大迭代 | 5（每轮 play + curation） |
| Play loops | 100 |
| Phase-M loops | 30 |
| 并行度 | 2 |
| Early-exit | 第一轮满分则跳过后续轮次 |
| 总耗时 | 41.9 小时 |

---

## 2. 核心创新：Focus Guard

ScienceWorld 的主要失败模式与 Jericho 不同。Jericho 是"不可逆死亡"（执行致命动作 → 游戏终止），而 ScienceWorld 是 **`focus on X` 中 X 错误 → 瞬间 -100 分**。同一 `focus on` 动作在不同任务中正确性不同（`focus on water` 在 boil-water 任务中正确，在 boil-lead 任务中错误）。

**Focus Guard 设计**：

1. Curator 在知识文件中用 `[FOCUS:target]` 标签记录经验证正确的 focus 目标。
2. Play agent 执行 `focus on Y` 时，Guard 从知识文件读取已验证目标：
   - Y 匹配已知正确目标 → 放行
   - Y 不匹配任何已知目标且存在已验证目标 → **拦截**（提示正确目标）
3. 同时保留 `[FATAL:...]` 标签拦截确认致命动作（如喝汞、触电）。

---

## 3. 总体结果

| 指标 | 值 |
|------|-----|
| 总任务数 | 211 |
| 获胜（满分） | 187 / 211 (89%) |
| Iter1 平均分 | 83.4 |
| 最终平均分 | 95.5 |
| TTL 提分 | **+12.1** |

### 迭代分布

| 迭代次数 | 任务数 | 占比 |
|----------|--------|------|
| 1 轮（首轮满分） | 148 | 70% |
| 2 轮 | 22 | 10% |
| 3 轮 | 6 | 3% |
| 4 轮 | 5 | 2% |
| 5 轮（全部用完） | 30 | 14% |

---

## 4. 按任务类别结果

| 类别 | 任务数 | 获胜 | Iter1 均分 | Final 均分 | TTL Δ |
|------|--------|------|-----------|-----------|-------|
| Matter (State Change) | 36 | 29 | 57.3 | 94.0 | **+36.7** |
| Measurement | 20 | 20 | 100.0 | 100.0 | +0.0 |
| Electricity | 30 | 25 | 88.8 | 97.0 | +8.3 |
| Classification | 40 | 40 | 99.0 | 100.0 | +1.0 |
| Biology (Growth) | 20 | 9 | 48.6 | 69.3 | **+20.7** |
| Chemistry | 26 | 26 | 95.1 | 100.0 | +4.9 |
| Biology (Lifespan) | 30 | 30 | 95.0 | 100.0 | +5.0 |
| Biology (Life Stages) | 9 | 8 | 68.6 | 95.3 | **+26.8** |

**关键发现**：
- **物态变化类（boil/freeze/melt）**：TTL 效果最强（+36.7），这些任务需要精确的 `focus on` 目标，首轮极易 -100。
- **测量/分类/化学**：GLM-5.2 首轮即可满分，TTL 几乎无作用。
- **生物生长（grow-fruit）**：最难的类别，10 个任务全军覆没，平均仅 42.2 分。

---

## 5. 按任务详细结果

| # | Task | Var | I1 | I2 | I3 | I4 | I5 | Best | Iters | Won |
|---|------|-----|----|----|----|----|----|------|-------|-----|
| 1 | boil | 021 | 78 | 78 | 83 | 85 | 52 | 85 | 5 | |
| 2 | boil | 022 | 80 | 80 | 80 | 83 | 87 | 87 | 5 | |
| 3 | boil | 023 | 0 | 85 | 85 | 85 | 80 | 85 | 5 | |
| 4 | boil | 024 | 8 | 100 | - | - | - | 100 | 2 | WIN |
| 5 | boil | 025 | 78 | 100 | - | - | - | 100 | 2 | WIN |
| 6 | boil | 026 | 7 | 100 | - | - | - | 100 | 2 | WIN |
| 7 | boil | 027 | 5 | 100 | - | - | - | 100 | 2 | WIN |
| 8 | boil | 028 | 5 | 100 | - | - | - | 100 | 2 | WIN |
| 9 | boil | 029 | 7 | 100 | - | - | - | 100 | 2 | WIN |
| 10 | change-the-state-of-matter-of | 021 | 100 | - | - | - | - | 100 | 1 | WIN |
| 11 | change-the-state-of-matter-of | 022 | 100 | - | - | - | - | 100 | 1 | WIN |
| 12 | change-the-state-of-matter-of | 023 | 0 | 0 | 0 | 1 | 100 | 100 | 5 | WIN |
| 13 | change-the-state-of-matter-of | 024 | 100 | - | - | - | - | 100 | 1 | WIN |
| 14 | change-the-state-of-matter-of | 025 | 100 | - | - | - | - | 100 | 1 | WIN |
| 15 | change-the-state-of-matter-of | 026 | 100 | - | - | - | - | 100 | 1 | WIN |
| 16 | change-the-state-of-matter-of | 027 | 100 | - | - | - | - | 100 | 1 | WIN |
| 17 | change-the-state-of-matter-of | 028 | 100 | - | - | - | - | 100 | 1 | WIN |
| 18 | change-the-state-of-matter-of | 029 | 100 | - | - | - | - | 100 | 1 | WIN |
| 19 | freeze | 021 | 48 | 48 | 48 | 48 | 48 | 48 | 5 | |
| 20 | freeze | 022 | 10 | 53 | 48 | 87 | 100 | 100 | 5 | WIN |
| 21 | freeze | 023 | 0 | 0 | 0 | 0 | 100 | 100 | 5 | WIN |
| 22 | freeze | 024 | 100 | - | - | - | - | 100 | 1 | WIN |
| 23 | freeze | 025 | 10 | 100 | - | - | - | 100 | 2 | WIN |
| 24 | freeze | 026 | 10 | 48 | 48 | 82 | 100 | 100 | 5 | WIN |
| 25 | freeze | 027 | 10 | 48 | 48 | 48 | 100 | 100 | 5 | WIN |
| 26 | freeze | 028 | 10 | 48 | 82 | 48 | 48 | 82 | 5 | |
| 27 | freeze | 029 | 48 | 48 | 48 | 48 | 48 | 48 | 5 | |
| 28 | melt | 021 | 100 | - | - | - | - | 100 | 1 | WIN |
| 29 | melt | 022 | 100 | - | - | - | - | 100 | 1 | WIN |
| 30 | melt | 023 | 100 | - | - | - | - | 100 | 1 | WIN |
| 31 | melt | 024 | 45 | 45 | 47 | 50 | 50 | 50 | 5 | |
| 32 | melt | 025 | 100 | - | - | - | - | 100 | 1 | WIN |
| 33 | melt | 026 | 100 | - | - | - | - | 100 | 1 | WIN |
| 34 | melt | 027 | 100 | - | - | - | - | 100 | 1 | WIN |
| 35 | melt | 028 | 5 | 100 | - | - | - | 100 | 2 | WIN |
| 36 | melt | 029 | 100 | - | - | - | - | 100 | 1 | WIN |
| 37 | measure-melting-point-known-substance | 327 | 100 | - | - | - | - | 100 | 1 | WIN |
| 38 | measure-melting-point-known-substance | 328 | 100 | - | - | - | - | 100 | 1 | WIN |
| 39 | measure-melting-point-known-substance | 329 | 100 | - | - | - | - | 100 | 1 | WIN |
| 40 | measure-melting-point-known-substance | 330 | 100 | - | - | - | - | 100 | 1 | WIN |
| 41 | measure-melting-point-known-substance | 331 | 100 | - | - | - | - | 100 | 1 | WIN |
| 42 | measure-melting-point-known-substance | 332 | 100 | - | - | - | - | 100 | 1 | WIN |
| 43 | measure-melting-point-known-substance | 333 | 100 | - | - | - | - | 100 | 1 | WIN |
| 44 | measure-melting-point-known-substance | 334 | 100 | - | - | - | - | 100 | 1 | WIN |
| 45 | measure-melting-point-known-substance | 335 | 100 | - | - | - | - | 100 | 1 | WIN |
| 46 | measure-melting-point-known-substance | 336 | 100 | - | - | - | - | 100 | 1 | WIN |
| 47 | use-thermometer | 405 | 100 | - | - | - | - | 100 | 1 | WIN |
| 48 | use-thermometer | 406 | 100 | - | - | - | - | 100 | 1 | WIN |
| 49 | use-thermometer | 407 | 100 | - | - | - | - | 100 | 1 | WIN |
| 50 | use-thermometer | 408 | 100 | - | - | - | - | 100 | 1 | WIN |
| 51 | use-thermometer | 409 | 100 | - | - | - | - | 100 | 1 | WIN |
| 52 | use-thermometer | 410 | 100 | - | - | - | - | 100 | 1 | WIN |
| 53 | use-thermometer | 411 | 100 | - | - | - | - | 100 | 1 | WIN |
| 54 | use-thermometer | 412 | 100 | - | - | - | - | 100 | 1 | WIN |
| 55 | use-thermometer | 413 | 100 | - | - | - | - | 100 | 1 | WIN |
| 56 | use-thermometer | 414 | 100 | - | - | - | - | 100 | 1 | WIN |
| 57 | power-component | 015 | 100 | - | - | - | - | 100 | 1 | WIN |
| 58 | power-component | 016 | 83 | 83 | 83 | 83 | 83 | 83 | 5 | |
| 59 | power-component | 017 | 83 | 83 | 83 | 100 | - | 100 | 4 | WIN |
| 60 | power-component | 018 | 83 | 83 | 83 | 83 | 83 | 83 | 5 | |
| 61 | power-component | 019 | 83 | 83 | 83 | 83 | 83 | 83 | 5 | |
| 62 | power-component-renewable-vs-nonrenewable-energy | 015 | 100 | - | - | - | - | 100 | 1 | WIN |
| 63 | power-component-renewable-vs-nonrenewable-energy | 016 | 58 | 58 | 100 | - | - | 100 | 3 | WIN |
| 64 | power-component-renewable-vs-nonrenewable-energy | 017 | 58 | 58 | 100 | - | - | 100 | 3 | WIN |
| 65 | power-component-renewable-vs-nonrenewable-energy | 018 | 58 | 100 | - | - | - | 100 | 2 | WIN |
| 66 | power-component-renewable-vs-nonrenewable-energy | 019 | 58 | 100 | - | - | - | 100 | 2 | WIN |
| 67 | test-conductivity | 675 | 100 | - | - | - | - | 100 | 1 | WIN |
| 68 | test-conductivity | 676 | 100 | - | - | - | - | 100 | 1 | WIN |
| 69 | test-conductivity | 677 | 100 | - | - | - | - | 100 | 1 | WIN |
| 70 | test-conductivity | 678 | 100 | - | - | - | - | 100 | 1 | WIN |
| 71 | test-conductivity | 679 | 100 | - | - | - | - | 100 | 1 | WIN |
| 72 | test-conductivity | 680 | 100 | - | - | - | - | 100 | 1 | WIN |
| 73 | test-conductivity | 681 | 100 | - | - | - | - | 100 | 1 | WIN |
| 74 | test-conductivity | 682 | 100 | - | - | - | - | 100 | 1 | WIN |
| 75 | test-conductivity | 683 | 100 | - | - | - | - | 100 | 1 | WIN |
| 76 | test-conductivity | 684 | 100 | - | - | - | - | 100 | 1 | WIN |
| 77 | test-conductivity-of-unknown-substances | 450 | 100 | - | - | - | - | 100 | 1 | WIN |
| 78 | test-conductivity-of-unknown-substances | 451 | 79 | 79 | 79 | 79 | 79 | 79 | 5 | |
| 79 | test-conductivity-of-unknown-substances | 452 | 100 | - | - | - | - | 100 | 1 | WIN |
| 80 | test-conductivity-of-unknown-substances | 453 | 100 | - | - | - | - | 100 | 1 | WIN |
| 81 | test-conductivity-of-unknown-substances | 454 | 100 | - | - | - | - | 100 | 1 | WIN |
| 82 | test-conductivity-of-unknown-substances | 455 | 79 | 79 | 79 | 100 | - | 100 | 4 | WIN |
| 83 | test-conductivity-of-unknown-substances | 456 | 100 | - | - | - | - | 100 | 1 | WIN |
| 84 | test-conductivity-of-unknown-substances | 457 | 79 | 79 | 79 | 100 | - | 100 | 4 | WIN |
| 85 | test-conductivity-of-unknown-substances | 458 | 79 | 100 | - | - | - | 100 | 2 | WIN |
| 86 | test-conductivity-of-unknown-substances | 459 | 83 | 83 | 83 | 83 | 83 | 83 | 5 | |
| 87 | find-animal | 225 | 100 | - | - | - | - | 100 | 1 | WIN |
| 88 | find-animal | 226 | 100 | - | - | - | - | 100 | 1 | WIN |
| 89 | find-animal | 227 | 75 | 83 | 100 | - | - | 100 | 3 | WIN |
| 90 | find-animal | 228 | 100 | - | - | - | - | 100 | 1 | WIN |
| 91 | find-animal | 229 | 100 | - | - | - | - | 100 | 1 | WIN |
| 92 | find-animal | 230 | 83 | 100 | - | - | - | 100 | 2 | WIN |
| 93 | find-animal | 231 | 100 | - | - | - | - | 100 | 1 | WIN |
| 94 | find-animal | 232 | 100 | - | - | - | - | 100 | 1 | WIN |
| 95 | find-animal | 233 | 100 | - | - | - | - | 100 | 1 | WIN |
| 96 | find-animal | 234 | 100 | - | - | - | - | 100 | 1 | WIN |
| 97 | find-living-thing | 225 | 100 | - | - | - | - | 100 | 1 | WIN |
| 98 | find-living-thing | 226 | 100 | - | - | - | - | 100 | 1 | WIN |
| 99 | find-living-thing | 227 | 100 | - | - | - | - | 100 | 1 | WIN |
| 100 | find-living-thing | 228 | 100 | - | - | - | - | 100 | 1 | WIN |
| 101 | find-living-thing | 229 | 100 | - | - | - | - | 100 | 1 | WIN |
| 102 | find-living-thing | 230 | 100 | - | - | - | - | 100 | 1 | WIN |
| 103 | find-living-thing | 231 | 100 | - | - | - | - | 100 | 1 | WIN |
| 104 | find-living-thing | 231 | 100 | - | - | - | - | 100 | 1 | WIN |
| 105 | find-living-thing | 233 | 100 | - | - | - | - | 100 | 1 | WIN |
| 106 | find-living-thing | 234 | 100 | - | - | - | - | 100 | 1 | WIN |
| 107 | find-non-living-thing | 225 | 100 | - | - | - | - | 100 | 1 | WIN |
| 108 | find-non-living-thing | 226 | 100 | - | - | - | - | 100 | 1 | WIN |
| 109 | find-non-living-thing | 227 | 100 | - | - | - | - | 100 | 1 | WIN |
| 110 | find-non-living-thing | 228 | 100 | - | - | - | - | 100 | 1 | WIN |
| 111 | find-non-living-thing | 229 | 100 | - | - | - | - | 100 | 1 | WIN |
| 112 | find-non-living-thing | 230 | 100 | - | - | - | - | 100 | 1 | WIN |
| 113 | find-non-living-thing | 231 | 100 | - | - | - | - | 100 | 1 | WIN |
| 114 | find-non-living-thing | 232 | 100 | - | - | - | - | 100 | 1 | WIN |
| 115 | find-non-living-thing | 233 | 100 | - | - | - | - | 100 | 1 | WIN |
| 116 | find-non-living-thing | 234 | 100 | - | - | - | - | 100 | 1 | WIN |
| 117 | find-plant | 225 | 100 | - | - | - | - | 100 | 1 | WIN |
| 118 | find-plant | 226 | 100 | - | - | - | - | 100 | 1 | WIN |
| 119 | find-plant | 227 | 100 | - | - | - | - | 100 | 1 | WIN |
| 120 | find-plant | 228 | 100 | - | - | - | - | 100 | 1 | WIN |
| 121 | find-plant | 229 | 100 | - | - | - | - | 100 | 1 | WIN |
| 122 | find-plant | 230 | 100 | - | - | - | - | 100 | 1 | WIN |
| 123 | find-plant | 231 | 100 | - | - | - | - | 100 | 1 | WIN |
| 124 | find-plant | 232 | 100 | - | - | - | - | 100 | 1 | WIN |
| 125 | find-plant | 233 | 100 | - | - | - | - | 100 | 1 | WIN |
| 126 | find-plant | 234 | 100 | - | - | - | - | 100 | 1 | WIN |
| 127 | grow-fruit | 093 | 34 | 34 | 39 | 30 | 30 | 39 | 5 | |
| 128 | grow-fruit | 094 | 30 | 36 | 34 | 39 | 39 | 39 | 5 | |
| 129 | grow-fruit | 095 | 29 | 29 | 41 | 37 | 41 | 41 | 5 | |
| 130 | grow-fruit | 096 | 34 | 43 | 43 | 43 | 41 | 43 | 5 | |
| 131 | grow-fruit | 097 | 36 | 45 | 41 | 41 | 41 | 45 | 5 | |
| 132 | grow-fruit | 098 | 25 | 37 | 43 | 43 | 45 | 45 | 5 | |
| 133 | grow-fruit | 099 | 34 | 41 | 39 | 37 | 39 | 41 | 5 | |
| 134 | grow-fruit | 100 | 36 | 43 | 34 | 43 | 43 | 43 | 5 | |
| 135 | grow-fruit | 101 | 45 | 41 | 39 | 45 | 37 | 45 | 5 | |
| 136 | grow-fruit | 102 | 29 | 36 | 32 | 39 | 41 | 41 | 5 | |
| 137 | grow-plant | 093 | 13 | 11 | 64 | 64 | 64 | 64 | 5 | |
| 138 | grow-plant | 094 | 5 | 62 | 100 | - | - | 100 | 3 | WIN |
| 139 | grow-plant | 095 | 100 | - | - | - | - | 100 | 1 | WIN |
| 140 | grow-plant | 096 | 64 | 66 | 100 | - | - | 100 | 3 | WIN |
| 141 | grow-plant | 097 | 61 | 61 | 61 | 100 | - | 100 | 4 | WIN |
| 142 | grow-plant | 098 | 36 | 63 | 100 | - | - | 100 | 3 | WIN |
| 143 | grow-plant | 099 | 100 | - | - | - | - | 100 | 1 | WIN |
| 144 | grow-plant | 100 | 61 | 63 | 58 | 63 | 100 | 100 | 5 | WIN |
| 145 | grow-plant | 101 | 100 | - | - | - | - | 100 | 1 | WIN |
| 146 | grow-plant | 102 | 100 | - | - | - | - | 100 | 1 | WIN |
| 147 | chemistry-mix | 024 | 100 | - | - | - | - | 100 | 1 | WIN |
| 148 | chemistry-mix | 025 | 100 | - | - | - | - | 100 | 1 | WIN |
| 149 | chemistry-mix | 026 | 100 | - | - | - | - | 100 | 1 | WIN |
| 150 | chemistry-mix | 027 | 100 | - | - | - | - | 100 | 1 | WIN |
| 151 | chemistry-mix | 028 | 100 | - | - | - | - | 100 | 1 | WIN |
| 152 | chemistry-mix | 029 | 100 | - | - | - | - | 100 | 1 | WIN |
| 153 | chemistry-mix | 030 | 42 | 100 | - | - | - | 100 | 2 | WIN |
| 154 | chemistry-mix | 031 | 100 | - | - | - | - | 100 | 1 | WIN |
| 155 | chemistry-mix-paint-secondary-color | 027 | 100 | - | - | - | - | 100 | 1 | WIN |
| 156 | chemistry-mix-paint-secondary-color | 028 | 100 | - | - | - | - | 100 | 1 | WIN |
| 157 | chemistry-mix-paint-secondary-color | 029 | 100 | - | - | - | - | 100 | 1 | WIN |
| 158 | chemistry-mix-paint-secondary-color | 030 | 100 | - | - | - | - | 100 | 1 | WIN |
| 159 | chemistry-mix-paint-secondary-color | 031 | 100 | - | - | - | - | 100 | 1 | WIN |
| 160 | chemistry-mix-paint-secondary-color | 032 | 100 | - | - | - | - | 100 | 1 | WIN |
| 161 | chemistry-mix-paint-secondary-color | 033 | 100 | - | - | - | - | 100 | 1 | WIN |
| 162 | chemistry-mix-paint-secondary-color | 034 | 100 | - | - | - | - | 100 | 1 | WIN |
| 163 | chemistry-mix-paint-secondary-color | 035 | 30 | 100 | - | - | - | 100 | 2 | WIN |
| 164 | chemistry-mix-paint-tertiary-color | 027 | 100 | - | - | - | - | 100 | 1 | WIN |
| 165 | chemistry-mix-paint-tertiary-color | 028 | 100 | - | - | - | - | 100 | 1 | WIN |
| 166 | chemistry-mix-paint-tertiary-color | 029 | 100 | - | - | - | - | 100 | 1 | WIN |
| 167 | chemistry-mix-paint-tertiary-color | 030 | 100 | - | - | - | - | 100 | 1 | WIN |
| 168 | chemistry-mix-paint-tertiary-color | 031 | 100 | - | - | - | - | 100 | 1 | WIN |
| 169 | chemistry-mix-paint-tertiary-color | 032 | 100 | - | - | - | - | 100 | 1 | WIN |
| 170 | chemistry-mix-paint-tertiary-color | 033 | 100 | - | - | - | - | 100 | 1 | WIN |
| 171 | chemistry-mix-paint-paint-tertiary-color | 034 | 100 | - | - | - | - | 100 | 1 | WIN |
| 172 | chemistry-mix-paint-tertiary-color | 035 | 100 | - | - | - | - | 100 | 1 | WIN |
| 173 | lifespan-longest-lived | 093 | 100 | - | - | - | - | 100 | 1 | WIN |
| 174 | lifespan-longest-lived | 094 | 100 | - | - | - | - | 100 | 1 | WIN |
| 175 | lifespan-longest-lived | 095 | 100 | - | - | - | - | 100 | 1 | WIN |
| 176 | lifespan-longest-lived | 096 | 100 | - | - | - | - | 100 | 1 | WIN |
| 177 | lifespan-longest-lived | 097 | 100 | - | - | - | - | 100 | 1 | WIN |
| 178 | lifespan-longest-lived | 098 | 100 | - | - | - | - | 100 | 1 | WIN |
| 179 | lifespan-longest-lived | 099 | 100 | - | - | - | - | 100 | 1 | WIN |
| 180 | lifespan-longest-lived | 100 | 100 | - | - | - | - | 100 | 1 | WIN |
| 181 | lifespan-longest-lived | 101 | 100 | - | - | - | - | 100 | 1 | WIN |
| 182 | lifespan-longest-lived | 102 | 100 | - | - | - | - | 100 | 1 | WIN |
| 183 | lifespan-longest-lived-then-shortest-lived | 093 | 100 | - | - | - | - | 100 | 1 | WIN |
| 184 | lifespan-longest-lived-then-shortest-lived | 094 | 83 | 100 | - | - | - | 100 | 2 | WIN |
| 185 | lifespan-longest-lived-then-shortest-lived | 095 | 100 | - | - | - | - | 100 | 1 | WIN |
| 186 | lifespan-longest-lived-then-shortest-lived | 096 | 100 | - | - | - | - | 100 | 1 | WIN |
| 187 | lifespan-longest-lived-then-shortest-lived | 097 | 100 | - | - | - | - | 100 | 1 | WIN |
| 188 | lifespan-longest-lived-then-shortest-lived | 098 | 83 | 100 | - | - | - | 100 | 2 | WIN |
| 189 | lifespan-longest-lived-then-shortest-lived | 099 | 83 | 100 | - | - | - | 100 | 2 | WIN |
| 190 | lifespan-longest-lived-then-shortest-lived | 100 | 100 | - | - | - | - | 100 | 1 | WIN |
| 191 | lifespan-longest-lived-then-shortest-lived | 101 | 100 | - | - | - | - | 100 | 1 | WIN |
| 192 | lifespan-longest-lived-then-shortest-lived | 102 | 100 | - | - | - | - | 100 | 1 | WIN |
| 193 | lifespan-shortest-lived | 093 | 100 | - | - | - | - | 100 | 1 | WIN |
| 194 | lifespan-shortest-lived | 094 | 50 | 100 | - | - | - | 100 | 2 | WIN |
| 195 | lifespan-shortest-lived | 095 | 100 | - | - | - | - | 100 | 1 | WIN |
| 196 | lifespan-shortest-lived | 096 | 100 | - | - | - | - | 100 | 1 | WIN |
| 197 | lifespan-shortest-lived | 097 | 100 | - | - | - | - | 100 | 1 | WIN |
| 198 | lifespan-shortest-lived | 098 | 100 | - | - | - | - | 100 | 1 | WIN |
| 199 | lifespan-shortest-lived | 099 | 50 | 100 | - | - | - | 100 | 2 | WIN |
| 200 | lifespan-shortest-lived | 100 | 100 | - | - | - | - | 100 | 1 | WIN |
| 201 | lifespan-shortest-lived | 101 | 100 | - | - | - | - | 100 | 1 | WIN |
| 202 | lifespan-shortest-lived | 102 | 100 | - | - | - | - | 100 | 1 | WIN |
| 203 | identify-life-stages-1 | 009 | 100 | - | - | - | - | 100 | 1 | WIN |
| 204 | identify-life-stages-1 | 010 | 100 | - | - | - | - | 100 | 1 | WIN |
| 205 | identify-life-stages-1 | 011 | 8 | 100 | - | - | - | 100 | 2 | WIN |
| 206 | identify-life-stages-1 | 012 | 83 | 100 | - | - | - | 100 | 2 | WIN |
| 207 | identify-life-stages-1 | 013 | 10 | 10 | 10 | 100 | - | 100 | 4 | WIN |
| 208 | identify-life-stages-2 | 006 | 100 | - | - | - | - | 100 | 1 | WIN |
| 209 | identify-life-stages-2 | 007 | 58 | 100 | - | - | - | 100 | 2 | WIN |
| 210 | identify-life-stages-2 | 008 | 58 | 58 | 58 | 58 | 58 | 58 | 5 | |
| 211 | identify-life-stages-2 | 009 | 100 | - | - | - | - | 100 | 1 | WIN |

---

## 6. 失败任务分析

24 个任务未达满分。按失败原因分类：

### 6.1 物态变化（温度控制困难）— 7 个

| 任务 | Var | 最佳分数 | 原因 |
|------|-----|---------|------|
| boil | 021 | 85 | boil lead：铅沸点 1749°C，blast furnace 无法达到 |
| boil | 022 | 87 | boil lead：同上，温度不足 |
| boil | 023 | 85 | boil lead：首轮 -100（focus 错误），TTL 恢复到 85 |
| freeze | 021 | 48 | freeze lead：放入 ultra cold freezer 但反复开关门破坏温度 |
| freeze | 028 | 82 | freeze caesium：iter3 意外用 blast furnace 得 82 分，但后续轮次被错误知识误导 |
| freeze | 029 | 48 | freeze caesium：同 028，反复开关 freezer 门 |
| melt | 024 | 50 | melt mercury：把 mercury 放进 freezer（方向完全相反） |

**根因**：这些任务需要精确的温度控制和长时间等待（不能反复开关容器门），wiki 知识难以表达这种动态物理过程。

### 6.2 电路接线 — 3 个

| 任务 | Var | 最佳分数 | 原因 |
|------|-----|---------|------|
| power-component | 016 | 83 | electric buzzer：电路接线不完整，反复 connect/disconnect |
| power-component | 018 | 83 | 同上 |
| power-component | 019 | 83 | 同上 |

**根因**：需要构建完整的闭合回路（电池 → wire → switch → device → wire → 电池），极性必须匹配。5 轮迭代均卡在 83 分。

### 6.3 生物生长 — 10 个

| 任务 | Var 范围 | 最佳分数范围 | 原因 |
|------|---------|-------------|------|
| grow-fruit | 093-102 | 39-45 | 需要长时间多步骤（种植、浇水、等待生长、结果），100 步限制内难以完成 |

**根因**：grow-fruit 需要极长的生长周期（数十个 tick），且步骤序列复杂。TTL 从 iter1 的 33.2 提升到 42.2，但仍不足以达到满分。

### 6.4 其他 — 4 个

| 任务 | Var | 最佳分数 | 原因 |
|------|-----|---------|------|
| test-conductivity-unknown | 451 | 79 | 未知物质导电性判断错误 |
| test-conductivity-unknown | 459 | 83 | 同上 |
| grow-plant | 093 | 64 | 唯一未获胜的 grow-plant |
| identify-life-stages-2 | 008 | 58 | 动物生命阶段识别错误 |

---

## 7. TTL 效果分析

### 7.1 经典成功案例

**boil var024**：iter1 仅 8 分（focus 错误或找不到物质）→ curator 提取正确路径 → iter2 满分（+92）

**change-the-state-of-matter-of var023**：iter1-4 持续低分（0→0→0→1）→ iter5 满分（+99）

**freeze var021→023**：iter1 完全失败（0 分），经过 5 轮学习最终满分

### 7.2 TTL 贡献量化

| 指标 | 值 |
|------|-----|
| Iter1 总分 | 17,598 / 21,100 |
| Final 总分 | 20,151 / 21,100 |
| TTL 净增 | +2,553 分 |
| TTL 相对提升 | +14.5% |
| 多轮迭代任务数 | 63 / 211 (30%) |
| 多轮任务中 TTL 成功率达满分 | 37 / 63 (59%) |

### 7.3 知识积累的正负效应

- **正向**：boil/freeze 类任务，首轮 focus 错误得 0-10 分，curator 记录正确 focus 目标后第二轮直接满分。
- **负向**：freeze var028，iter3 意外通过 blast furnace 得 82 分（实际方向错误），该知识被写入 wiki 后误导后续迭代，iter4-5 回落到 48 分。

---

## 8. 结论

1. **Wiki-Evolve 框架成功迁移到 ScienceWorld**，整体达到 89% 获胜率（187/211）、95.5% 平均分。

2. **Focus Guard 是核心创新**：ScienceWorld 的 `focus on X` 错误导致 -100 分是最主要的失败模式。Focus Guard 通过 curator 记录经验证的正确目标，在工具层拦截错误 focus，使物态变化类任务的 TTL 效果达到 +36.7 分。

3. **GLM-5.2 基础能力强**：70% 的任务首轮即满分，TTL 的价值集中在 30% 需要多轮学习的任务上。

4. **主要瓶颈**：grow-fruit（长周期生物生长）、power-component（复杂电路）、高沸点物质（boil lead）是当前框架难以解决的。
