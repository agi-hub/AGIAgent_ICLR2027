# 最新版本代码实验汇总 (ablations_summary.md)

> 代码版本: 最新版（query_wm + World Model、FATAL 修复版、Loop Detection 修复版、wiki_memory_read 全文返回、max_results cap=3、Knowledge-Experience Evidence 链接、Gemini 兼容修复）
>
> 通用配置: 10 迭代 × 110 步/迭代 | 游戏池: Detective(13), Library(24), Zork1(51), Zork3(53), Balances(8), Temple(44)
>
> 日期: 2026-08-20

---

## 1. 实验总表

### 1.1 GLM-5.2 系列

| 实验 | 条件 | 游戏数 | TOTAL avg | 数据目录 (benchmark_results) | Wiki 目录 | 消融参数 |
|---|---|---|---|---|---|---|
| abl19_glm52_full | **full** | 6 | 432.8(五跑之一; n=5 统计见 §3.5) | `data/benchmark_results/abl19_glm52_full/` | `data/default/general/wiki/abl19_glm52_full/` | (无) |
| abl25/26/27/28_glm52_full_rerun×4 | **full 复跑 ×4**(一致性检验) | 6 | **归一化均值 47.0±6.6%**(n=5, 论文口径) | `data/benchmark_results/abl2{5..8}_glm52_full_*/` | 同名 wiki 目录 | 同 abl19 完整配置(含 emulator-crash 修复: abl26 Detective ep9 剔除补测) |
| abl21_glm52_no_knowledge | w/ (Exp, WM), w/o (Know, HP) | 6 | 379.5 | `data/benchmark_results/abl21_glm52_no_knowledge/` | `data/default/general/wiki/abl21_glm52_no_knowledge/` | `--ablation no_knowledge` + experiences STRATEGY prompt |
| abl19_glm52_no_wiki_wm | w/ WM, w/o (Know, Exp, HP) | 6 | 180.1 | `data/benchmark_results/abl19_glm52_no_wiki_wm/` | `data/default/general/wiki/abl19_glm52_no_wiki_wm/` | `--ablation no_wiki` + WM guard 已移除 |
| abl19_glm52_no_wiki | Naive ReAct | 6 | 152.7 | `data/benchmark_results/abl19_glm52_no_wiki/` | `data/default/general/wiki/abl19_glm52_no_wiki/` | `--ablation no_wiki` |
| abl22_glm52_react | 纯 ReAct（无脚手架） | 6 | 184.8 (best 387) | `data/benchmark_results/abl22_glm52_react/` | `data/default/general/wiki/abl22_glm52_react/` | `--ablation no_wiki` + `AGIA_REACT_PROMPT=1` + `AGIA_DISABLE_LOOP_DETECT=1` |
| abl23_glm52_autom | 纯 ReAct + AutoManual 思想 ([NeurIPS 2024](https://arxiv.org/abs/2405.16247), [repo](https://github.com/minghchen/automanual)) | 6 | 327.4 (best 509) | `data/benchmark_results/abl23_glm52_autom/` | `data/default/general/wiki/abl23_glm52_autom/` | abl22 全部参数 + `AGIA_CURATOR_STYLE=autom` |
| abl24_glm52_recmem | RecMem 原始方案 ([ACL 2026 Findings](https://github.com/CaiusDai/RecMem), 外部基线, 修复版) | 6 | 206.7 (best 323) | `~/recmem_abl24_glm52/` | `~/recmem_abl24_glm52/`(Qdrant 三层存储) | `~/RecMem/run_ablation24.sh`,同 6 游戏 × 10 局 × 110 步,记忆=RecMem 递归固化+三路检索; temp=1.0 对齐; Zork1 ep10 于 94/110 步冻结 |
| abl19_glm52_no_knowledge | ⚠️ 旧版 (prompt 缺陷) | 6 | 162.9 | `data/benchmark_results/abl19_glm52_no_knowledge/` | `data/default/general/wiki/abl19_glm52_no_knowledge/` | `--ablation no_knowledge`（prompt 写死查 knowledge，Experience 未生效） |

### 1.2 DeepSeek-Pro 系列（官方最新版模型）

| 实验 | 条件 | 游戏数 | TOTAL avg | 数据目录 | Wiki 目录 | 消融参数 |
|---|---|---|---|---|---|---|
| abl20_pro_full | **full** | 6 | 325.1 | `data/benchmark_results/abl20_pro_full/` | `data/default/general/wiki/abl20_pro_full/` | (无) |
| abl16_pro_no_wiki | Naive ReAct | 6 | 256.6 | `data/benchmark_results/abl16_pro_no_wiki/` | `data/default/general/wiki/abl16_pro_no_wiki/` | `--ablation no_wiki` |
| abl16_pro_full | ⚠️ 旧版模型 | 9 | 404.0 (8游戏) | `data/benchmark_results/abl16_pro_full/` | `data/default/general/wiki/abl16_pro_full/` | (无) — 模型已被官方更新，不可与 abl16_pro_no_wiki 直接对比 |

### 1.3 Gemini-2.5-Flash 系列

| 实验 | 条件 | 游戏数 | TOTAL avg | 数据目录 | Wiki 目录 | 消融参数 |
|---|---|---|---|---|---|---|
| abl18_gemini_full | **full** | 6 | 258.1 | `data/benchmark_results/abl18_gemini_full/` | `data/default/general/wiki/abl18_gemini_full/` | (无), streaming=False, Tool_calling_format=True |
| abl18_gemini_test2 | full (Zork1 重跑) | 1 | 36.5 (Zork1) | `data/benchmark_results/abl18_gemini_test2/` | `data/default/general/wiki/abl18_gemini_test2/` | (无), streaming=False, Tool_calling_format=False, json 解析 |

---

## 2. 组件配置矩阵

| 条件 | Knowledge 检索 | Experience 检索 | World Model (query_wm) | FATAL 拦截 | Loop Detection | 策展纪律 | Manual 注入 |
|---|---|---|---|---|---|---|---|
| full | ✅ | ✅ | ✅ | ✅ | ✅ | 基础 | ❌ |
| w/ (Exp, WM), w/o (Know, HP) | ❌ | ✅ | ✅ | ❌ | ✅ | 基础 | ❌ |
| w/ WM, w/o (Know, Exp, HP) | ❌ | ❌ | ✅ | ❌ | ✅ | 基础 | ❌ |
| Naive ReAct | ❌ | ❌ | ❌ | ❌ | ✅ | 基础 | ❌ |
| 纯 ReAct (abl22) | ❌ | ❌ | ❌ | ❌ | ❌ | 基础 | ❌ |
| 纯 ReAct + AutoManual (abl23) | ❌ | ❌ | ❌ | ❌ | ❌ | **AutoManual 式** | **✅（prompt 直读全文，6000 字符上限）** |

> abl23 的 Manual 注入不经过任何检索工具：phase_m 产出的 knowledge 文件由 runner 直接嵌入 play prompt（attempt ≥ 2），即 AutoManual 的 manual-as-context 设计。策展纪律 = 30 条目预算+合并规则、WIKI_GAP/EXECUTION_ERROR/EXPLORATION 三分支失败归因、[ok N/M] 滚动验证标记（`apps/tale_jericho/prompts/phase_m_prompt_autom.txt`，由 `AGIA_CURATOR_STYLE=autom` 门控）。

---

## 3. 核心对比结果

### 3.1 GLM-5.2 四条件消融

| Game | max | full | w/ (Exp, WM)<br>w/o (Know, HP) | w/ WM<br>w/o (Know, Exp, HP) | Naive ReAct |
|---|---|---|---|---|---|
| Detective | 360 | 297.0 | 273.0 | 80.0 | 60.0 |
| Library | 30 | 29.1 | 16.0 | 21.1 | 22.6 |
| Zork1 | 350 | 61.6 | 59.1 | 53.1 | 45.6 |
| Zork3 | 7 | 3.6 | 3.9 | 3.0 | 3.4 |
| Balances | 51 | 19.5 | 14.0 | 14.5 | 14.0 |
| Temple | 35 | 22.0 | 13.5 | 8.4 | 7.1 |
| **TOTAL avg** | | **432.8** | **379.5** | **180.1** | **152.7** |
| **Δ vs Naive ReAct** | | +183% | +148% | +18% | 基线 |

### 3.2 DeepSeek-Pro Full vs Naive ReAct（同版本模型）

| Game | max | full (abl20) | Naive ReAct (abl16_pro_no_wiki) | Δ |
|---|---|---|---|---|
| Detective | 360 | 208.0 | 150.0 | +58.0 |
| Library | 30 | 25.3 | 23.5 | +1.8 |
| Zork1 | 350 | 52.2 | 55.8 | -3.6 |
| Zork3 | 7 | 2.9 | 2.8 | +0.1 |
| Balances | 51 | 22.5 | 14.0 | +8.5 |
| Temple | 35 | 14.2 | 10.5 | +3.7 |
| **TOTAL avg** | | **325.1** | **256.6** | **+27%** |

### 3.3 纯 ReAct 基线上的 AutoManual 思想消融（abl22 vs abl23）

| Game | max | 纯 ReAct (abl22) | +AutoManual (abl23) | full (abl19) |
|---|---|---|---|---|
| Detective | 360 | 74.0 (best 130) | **226.0 (best 350)** | 297.0 (best 340) |
| Library | 30 | 31.4 (best 130) | 14.7 (best 30) | 29.1 (best 30) |
| Zork1 | 350 | 56.3 (best 84) | 51.5 (best 85) | 63.6 (best 99) |
| Zork3 | 7 | 2.3 (best 3) | **2.7 (best 4)** | 3.6 (best 5) |
| Balances | 51 | 11.5 (best 20) | **17.5 (best 20)** | 19.5 (best 20) |
| Temple | 35 | 9.3 (best 20) | **15.0 (best 20)** | 22.0 (best 25) |
| **TOTAL avg** | | **184.8** | **327.4 (+77%)** | 434.8 |
| **TOTAL best** | | 387 | **509** | 519 |

**单一变量**: abl23 = abl22 + `AGIA_CURATOR_STYLE=autom`(AutoManual 三思想:(a) phase_m 策展纪律——30 条目预算+合并、WIKI_GAP/EXECUTION_ERROR/EXPLORATION 失败归因、[ok N/M] 滚动验证;(b) manual 以全文(≤6000 字符)直接注入 play prompt,不引入任何检索工具/护栏/循环检测)。

**结论**:
1. **+77% vs 纯 ReAct**——在零检索工具、零硬护栏的纯 prompt 注入下,AutoManual 式策展+manual 注入拿到 full 管线 57% 的 avg 收益(+142.6 / +250.0)。
2. **best 口径下逼近 full**(509 vs 519, -1.9%)——manual 注入主要提升上限;avg 差距(327 vs 435)来自无 FATAL 硬拦截时 EXECUTION_ERROR 局(Detective 10 局中 2 局 0 分,死在已知陷阱),这正是归因体系标记但纯 prompt 无法强制执行的场景。
3. **Library 双向现象**: abl22 的 130 是真实解局(Jericho Library 满分可超 30,任务 max 标注偏低);abl23 拿到 2 次满分 30 但也有 3 局 0 分(manual 引导下速通路径遇随机事件失败)。avg 14.7<31.4 主要由 0 分局拖累——与 Detective 的 EXECUTION_ERROR 局同源。
4. **知识产物质量**: 最终 knowledge 文件带 [ok 6/6] 累积验证、CONDITIONAL 条件标注(bat room 抢夺)、多步路径合并条目,可追溯 evidence 链接完整——比 abl22 的同目录文件结构化程度显著更高。

> 完整实验文档(理论原理 / 实现细节 / 逐局得分 / 与 full 的分层对比): `abl23_autom_experiment.md`。

### 3.4 RecMem 外部基线（abl24, 修复版数据）

| Game | max | RecMem (abl24) | 纯 ReAct (abl22) | +AutoManual (abl23) | full (abl19) |
|---|---|---|---|---|---|
| Detective | 360 | **118.0** (best 200) | 74.0 | 226.0 | 297.0 |
| Library | 30 | 19.5 (best 21) | 31.4 | 14.7 | 29.1 |
| Zork1 | 350 | 46.5 (best 64) | 56.3 | 51.5 | 63.6 |
| Zork3 | 7 | 2.3 (best 3) | 2.3 | 2.7 | 3.6 |
| Balances | 51 | 10.5 (best 20) | 11.5 | 17.5 | 19.5 |
| Temple | 35 | **9.9** (best 15) | 9.3 | 15.0 | 22.0 |
| **TOTAL avg** | | **206.7 (+11.9%)** | 184.8 | **327.4** | **434.8** |
| **TOTAL best** | | 323 | 387 | 509 | 519 |

> Zork1 第 10 局在用户要求下于第 94/110 步冻结(当时 best=39,已计入)。逐局序列——Detective: 30,190,90,90,80,40,190,200,180,90;Balances: 10,5,5,5,5,10,15,15,15,20(爬升可见);Zork1: 39,64,50,45,44,45,39,50,50,39。

**配置**: 同协议(6 游戏 × 10 局 × 110 步, GLM-5.2, temperature=1.0 与 abl 各臂一致);记忆 = RecMem 原始方案(ACL 2026 Findings,递归触发固化 + 三层 subconscious/episodic/semantic + Qdrant 持久化,固化/提炼 prompt 为原版对话摘要风格未改)。运行: `~/RecMem/run_ablation24.sh`,数据: `~/recmem_abl24_glm52/`,分析: `~/RecMem/analyze_ablation24.py`。

**⚠️ 历史勘误(2026-08-24)**: 首轮 abl24 数据(198.4 avg)作废——适配器存在两个 bug:(1) GLM-5.2 推理模型偶发返回空 content 导致 `splitlines()[0]` 崩溃,49/60 局被提前中止(Balances/Zork1 全中,平均仅跑 3-24 步);(2) temperature 0.2 未与 abl 臂对齐(应为 1.0)。修复(空响应重试+`look` 兜底、temp=1.0)后重跑,零中止。表中为修复版数据。

**结论(修复版)**:
1. **RecMem +11.9% vs 纯 ReAct**(206.7 vs 184.8),远低于 abl23(+77%)与 full(+135%)——通用对话记忆方案直接迁移到文字冒险,收益有限但方向为正。
2. **记忆积累可见但天花板低**: Balances 逐局爬升至 20(=abl22 best 持平)、Zork1 ep2 冲到 64 后回落到 39-50 震荡——知识能召回(已验证),但对话式 semantic("user did X")无 [FATAL]/房间条件语义,死亡知识无法阻止重复冒险;Detective 90→200 的震荡同理。
3. **分游戏互有胜负**: Detective(118 vs 74)、Temple(9.9 vs 9.3)领先;Library(19.5 vs 31.4)、Zork1(46.5 vs 56.3)落后——Library 类精确多步序列任务上,无结构化 ordering 知识的记忆反而干扰;与 abl23 的 Library 反例(14.7)同向,进一步支持"记忆收益取决于知识结构语义而非记忆有无"。
4. **对照链完整**(各臂单跑口径): 纯 ReAct 184.8 → 通用对话记忆(RecMem) 206.7 → 游戏结构化知识注入(AutoManual) 327.4 → full 管线 434.8(单跑 abl19;n=5 归一化口径见 §3.5: full 47.0% vs 各臂, 排序不变)。四臂证据支持核心论点:位置条件化 + 致命性 + 可靠性标注的结构知识,才是文字冒险记忆系统的关键,而非记忆机制本身。

### 3.5 full 五跑统计(n=5, 2026-09-06 定稿)

五次独立 full 复跑(abl19/25/26*/27/28,同配置: GLM-5.2 × 6 游戏 × 10 局 × 110 步;abl26 剔除 1 例 emulator-crash 局并补测),统一论文口径(**每游戏 10 局 avg → ÷max → 六游戏平均**):

| run | 全程平均% | 末次尝试% | 后5轮% | best 合计 |
|---|---|---|---|---|
| abl19 | 58.4 | 65.8 | 63.5 | 519 |
| abl25 | 43.3 | 56.7 | 50.3 | 512 |
| abl26* | 47.5 | 49.8 | 52.6 | 503 |
| abl27 | 42.0 | 52.7 | 50.4 | 504 |
| abl28 | 44.1 | 65.3 | 55.2 | 563 |
| **mean±std** | **47.0±6.6** | **58.1±7.3** | **54.4±5.5** | **520.2±24.8** |

**结论**:
1. **full 论文口径定稿为 47.0±6.6%**(逐游戏: Detective 68.6±10.2 / Library 82.4±14.6 / Zork1 20.3±2.6 / Zork3 35.4±12.1 / Balances 33.7±3.6 / Temple 41.8±11.9)。
2. **上限高度可复现**: best 合计五跑 503-563(std 仅 24.8),全部 >500;Detective 五跑 best 全部 340-360,abl28 达成首个 360 完美通关,Library(abl28 55)与 Zork1(abl28 110)历史新高均出现在五跑中。
3. **方差来源是学习速度而非学习能力**: 末次尝试 std(7.3)与后5轮 std(5.5)远小于中途(ep3-5 std 10-12.6)——Detective 通关路线在第 3-6 局之间习得的先后,决定全程平均水位。
4. **n=5 对照(全程平均口径)**: full 47.0±6.6 vs w/o PM 33.6(**+13.4pp**)、AutoManual 40.4(+6.6)、EvoTest 本地 35.8(+11.2)、RecMem 32.1(+14.9)、TALES 45.0(+2.0)、EvoTest 论文 G 47.0(持平);**末次尝试 58.1±7.3 超过 EvoTest 论文 G(47.0)与 C(50.0)**——1/5 迭代预算的开源模型收敛后反超强模型长预算。

迭代曲线数据: `figs_data/full_5runs_curve.csv`;图(均值点线 ± std error bar): `figs_data/full_5runs_curve.pdf/.png`(绘制脚本 `figs_data/plot_full_5runs_curve.py`)。五跑曲线形态一致: ep1 约 31% → ep4-6 跃迁(路线知识固化)→ ep9-10 平台 58-59%,跨 run 方差从 ep3 峰值 12.6 收敛到末段 5-7。

---

## 4. 运行命令参考

### GLM-5.2

```bash
# full
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 --experiment-name <name>

# w/ (Exp, WM), w/o (Know, HP)
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 --experiment-name <name> \
  --ablation no_knowledge

# w/ WM, w/o (Know, Exp, HP) — 需要先移除 no_wiki 的 WM guard
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 --experiment-name <name> \
  --ablation no_wiki

# Naive ReAct
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 --experiment-name <name> \
  --ablation no_wiki
```

### DeepSeek-Pro

```bash
# 同上，但使用 apps/tale_jericho_pro/run_all_tasks.py
```

### Gemini-2.5-Flash

```bash
# 同上，但使用 apps/tale_jericho_gemini/run_all_tasks.py
# config 要求: streaming=False, Tool_calling_format=False, tool_call_parse_format=json
```

### 纯 ReAct + AutoManual 思想 (abl23)

```bash
bash apps/tale_jericho/run_ablations23_autom.sh
# 等价于手动:
AGIA_REACT_PROMPT=1 AGIA_DISABLE_LOOP_DETECT=1 AGIA_CURATOR_STYLE=autom \
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl23_glm52_autom --ablation no_wiki
```

---

## 5. 注意事项

1. **abl19_glm52_no_knowledge 已被 abl21 取代**——旧实验的 play prompt 写死查 knowledge，Experience 检索未生效。
2. **abl16_pro_full 使用旧版 DeepSeek 模型**——官方更新后不可与 abl16_pro_no_wiki (新版模型) 直接对比。有效对照为 abl20_pro_full vs abl16_pro_no_wiki。
3. **WM-only 条件需要代码修改**——默认 `--ablation no_wiki` 同时禁用 WM，需移除 `tale_jericho_tools.py` 中的 WM guard 后再跑。
4. **Gemini 配置特殊**——必须 `streaming=False`（避免 hallucination 检测误报）+ `Tool_calling_format=False`（避免原生工具调用不稳定）。
5. **Phase Records 格式**——`phase_records.json` 是扁平 list（非嵌套），每项含 `play_current_score` 等字段。
6. **abl23 环境事件**——venv 的 openai 曾被外部降级到 0.27.7（连带 pydantic 1.10），导致 tales/gymnasium 启动失败（`field_validator` 缺失）；已恢复 openai 2.41.1 + pydantic 2.13.4。若复现"pydantic import error"，先查 venv 依赖是否被动过。
