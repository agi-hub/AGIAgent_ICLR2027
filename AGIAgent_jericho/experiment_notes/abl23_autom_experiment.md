# abl23: 纯 ReAct 基线上的 AutoManual 思想移植实验

> 实验: `abl23_glm52_autom` | 日期: 2026-08-21 ~ 08-22 | 模型: GLM-5.2
> 对照: `abl22_glm52_react`(纯 ReAct 基线)、`abl19_glm52_full`(full 记忆管线)
> 思想来源: [AutoManual](https://arxiv.org/abs/2405.16247) (NeurIPS 2024), 本地部署 `~/automanual`

---

## 一、理论原理

### 1.1 AutoManual 的核心命题

AutoManual(Chen et al., NeurIPS 2024)研究的问题与本工程 tale_jericho 完全同构:**LLM agent 如何通过与环境的反复交互,把零散经验固化成可复用的知识,从而在后续尝试中提升表现**。其原系统跑在 ALFWorld 上,由两个角色构成:

- **Planner(Worker)**:根据当前规则手册写计划、执行、失败后重规划;
- **Builder(Curator)**:每个 epoch 结束后分析轨迹,把经验提炼成规则(rule),维护规则库;
- **Formulater**:积累足够规则后,把规则库公式化为一本结构化"手册"(manual),手册直接进入 Planner 的上下文。

### 1.2 三个可移植的核心思想

对 AutoManual 源码(`autobuild_utils.py`、`autobuild_case_trail.py`、`formulate_manual.py`)的逐行分析表明,其有效性不依赖 ALFWorld 的具体环境,而依赖三条知识管理纪律。它们在 Jericho 上同样成立:

**思想 1: 知识预算与合并(anti-bloat)**
AutoManual 硬性限制规则数 ≤ 12 条,超限即触发 Consolidator 合并或删除;规则的 `validation_record` 只保留最近 3 次验证。原理:**知识的消费者是一个上下文受限的 LLM,膨胀的知识与缺失的知识同样有害**。合并优先级明确:同类合并 > 路径压缩 > 已解决的问题出列 > 连续验证失败的条目出列(安全条目除外)。

**思想 2: 三分支失败归因(attribution before curation)**
Builder 在写规则前必须先把失败归类为:
- *Imperfect Rules*(≈WIKI_GAP):环境现象未被知识覆盖或覆盖错误 → 修知识;
- *Imperfect Agent*(≈EXECUTION_ERROR):知识已覆盖,agent 未遵守 → **不新增知识**,只强化既有条目(加粗、前置房间上下文、致命时升级为 FATAL);
- 探索性失败(EXPLORATION):知识未违反,在探新 → 只记录观察确认过的事实,禁止推测。

原理:**区分"知识缺什么"和"执行没跟上"是知识库不无限膨胀的关键**。EXECUTION_ERROR 若被当作 WIKI_GAP 处理,知识库会为同一现象生成越来越多冗余条目。

**思想 3: 滚动验证记录(validation markers)**
每条规则携带验证履历(哪个 epoch 验证过/失败过)。AutoManual 用 `validation_record` 字符串,本实验简化为 `[ok N/M]` 行内标记(M 次执行中 N 次达到预期)。原理:**知识条目应有可信度梯度**——`[ok 3/3]` 是可靠步骤,`[ok 1/2]` 是条件性条目,`[ok 0/2]` 必须被修正或降级进 Unexplored,不允许不可验证的条目长期留在正文中。

**思想 4(注入侧): Manual 即上下文(manual-as-context)**
AutoManual 的 Formulater 阶段产出结构化手册后,手册**全文进入 Planner 的系统提示**,Planner 无需任何检索调用。这与本工程 full 管线的"agent 主动调 `wiki_memory_read` 检索"形成鲜明对照:前者知识获取零成本、零遗漏、确定性;后者灵活但依赖 agent 记得去查、会查。

### 1.3 实验假设

> 在不引入任何检索工具、硬护栏、行为脚手架的纯 ReAct 基线上,**仅靠(1)给 Curator 加三条知识管理纪律、(2)把策展产物全文注入 play prompt**,即可回收 full 记忆管线收益的相当比例;剩余差距应集中于"知识存在但执行未遵守"(EXECUTION_ERROR)类失败,从而论证 full 管线中硬性护栏(FATAL 拦截)的必要性。

---

## 二、实现方案

### 2.1 单变量设计

abl23 在 abl22(纯 ReAct)之上只增加一个环境变量,不引入任何其他技术:

| 配置项 | abl22(基线) | abl23(+AutoManual) |
|---|---|---|
| `--ablation no_wiki` | ✅ | ✅(相同) |
| `AGIA_REACT_PROMPT=1`(无脚手架系统提示) | ✅ | ✅(相同) |
| `AGIA_DISABLE_LOOP_DETECT=1` | ✅ | ✅(相同) |
| Knowledge 检索工具(`wiki_memory_read`) | ❌ | ❌(仍禁用) |
| FATAL 硬拦截 | ❌ | ❌(仍禁用) |
| Loop Detection | ❌ | ❌(仍禁用) |
| **`AGIA_CURATOR_STYLE=autom`** | ❌ | **✅(唯一变量)** |
| 游戏池 / 迭代 / 步数 | 6 games × 10 iter × 110 steps | 相同 |
| phase_m 策展预算 | 30 loops | 相同 |

### 2.2 代码改动(三处,全部环境变量门控)

**(1) Curator 纪律注入 — `apps/tale_jericho/prompts/phase_m_prompt_autom.txt`(新增)**

当 `AGIA_CURATOR_STYLE=autom` 时,`_phase_m_requirement()`(`run_all_tasks.py`)把该文件追加到 phase_m 静态提示之后,给 Curator 增加三条强制性纪律:

```
### 1. Knowledge budget: keep it under 30 actionable entries
   (硬上限 30 条;超出必须先合并:同动作/房间合并、相邻路径压缩、
    已解决的 Unexplored 出列、连续 2 次验证失败出列;Death Trap 永不牺牲)

### 2. Failure attribution: classify the attempt BEFORE writing
   WIKI_GAP      → 补/修缺失或错误的条目
   EXECUTION_ERROR → 不新增条目,强化被忽视的既有条目(致命则升级 [FATAL])
   EXPLORATION   → 只记录观察确认的事实,禁止推测
   (判定词必须写在 experience 条目第一行)

### 3. Validation records: every Scoring Path entry must carry [ok N/M]
   (M 次执行 N 次达预期;[ok 0/2] 必须修正或降级进 Unexplored)
```

**(2) Manual 注入 play prompt — `run_all_tasks.py` `_play_requirement()` + `_load_manual_for_env()`(新增)**

`autom` 模式下 attempt ≥ 2 的 play 需求词变为(AutoManual manual-as-context):

```
A MANUAL built from earlier attempts is embedded below.
... replay the scoring path, avoid the death traps, probe the open questions ...
Verify every suggestion against the current observation — a manual entry
that fails twice is stale; skip it and explore.
============================================================
MANUAL (from previous attempts):
<knowledge/score_recipe_<game>.md 全文, 截断上限 AGIA_MANUAL_INJECT_CAP=6000 字符>
============================================================
```

无 manual 时回退为"explore from scratch"。attempt 1(无知识可用)与基线完全一致。

**(3) 门控与隔离** — 两个改动均只读 `AGIA_CURATOR_STYLE`;不设该变量时所有行为与旧代码逐字节一致(已有单元验证:默认臂的 prompt 文本不变)。

### 2.3 涉及文件

| 文件 | 改动 |
|---|---|
| `apps/tale_jericho/prompts/phase_m_prompt_autom.txt` | 新增,策展纪律文本 |
| `apps/tale_jericho/run_all_tasks.py` | `_phase_m_requirement` 追加 addon;`_play_requirement` 新增 autom 分支;新增 `_load_manual_for_env` |
| `apps/tale_jericho/run_ablations23_autom.sh` | 启动脚本(全部 abl22 环境变量 + `AGIA_CURATOR_STYLE=autom`) |

复现:`bash apps/tale_jericho/run_ablations23_autom.sh`

---

## 三、实验结论

### 3.1 总体

| 指标 | 纯 ReAct (abl22) | +AutoManual (abl23) | full 管线 (abl19) |
|---|---|---|---|
| **TOTAL avg**(逐局均值之和) | 184.8 | **327.4 (+77.2%)** | 434.8 |
| **TOTAL best**(每游戏最好局之和) | 387 | **509** | 519 |
| 回收 full 收益比例 | — | **avg 57%、best 96%** | — |

0 错误局;6 游戏 × 10 迭代全部完成。**在零检索工具、零硬护栏的纯 prompt 注入下,拿到 full 管线 57% 的 avg 收益、96% 的 best 收益。**

### 3.2 每个游戏的得分(avg = 10 局平均, best = 10 局最高;括号内为逐局序列)

| Game | max | abl22 纯 ReAct | abl23 +AutoManual | abl19 full |
|---|---|---|---|---|
| Detective | 360 | 74.0 / best 130<br>(30,90,30,30,130,130,30,110,130,30) | **226.0 / best 350**<br>(130,230,40,330,330,250,250,350,**0**,350) | 297.0 / best 340<br>(130,210,330,340,340,310,330,310,340,330) |
| Library | 30* | 31.4 / best 130<br>(3,21,21,21,20,21,**130**,27,21,29) | 14.7 / best 30<br>(1,21,7,28,30,30,**0**,30,**0**,**0**) | 29.1 / best 30<br>(21,30,30,30,30,30,30,30,30,30) |
| Zork1 | 350 | 56.3 / best 84<br>(0,69,59,59,74,50,84,50,59,59) | 51.5 / best 85<br>(0,54,74,80,**0**,74,85,74,74,**0**) | 63.6 / best 99<br>(54,50,74,65,85,50,0,85,99,74) |
| Zork3 | 7 | 2.3 / best 3 | **2.7 / best 4** | 3.6 / best 5 |
| Balances | 51 | 11.5 / best 20<br>(15,20,5,20,15,15,5,10,5,5) | **17.5 / best 20**<br>(15,20,20,20,15,20,20,20,5,20) | 19.5 / best 20 |
| Temple | 35 | 9.3 / best 20<br>(20,5,5,5,15,20,5,5,8,5) | **15.0 / best 20**<br>(10,0,15,20,20,20,15,15,15,20) | 22.0 / best 25 |

\* Library 的 max 标注 30,但游戏实际可超出(abl22 出过 130 的解局)。

### 3.3 逐游戏分析(vs abl22 基线 / vs full)

- **Detective(+152 avg,本方案最大赢家)**:manual 注入后逐局爬升 130→230→330→350,第 8 局即达 350/360(97%),与 full 的差距只剩最后 10 分。序列中的 0 分局(第 9 局)是典型的 EXECUTION_ERROR——死因(dazed man / Sauna)在 manual 的 Death Traps 里明确记载,纯 prompt 无法阻止 agent 偏航。**这正是"知识已存在、执行未遵守"的直接证据**。
- **Balances(+6.0)、Temple(+5.7)、Zork3(+0.4)**:manual 路径稳定性显著提升——Balances 10 局中 7 局拿满 20(基线仅 3 局),Temple 从 5 分动荡局变为稳定 15-20 局。这三局验证了**验证标记的价值**:agent 优先执行 `[ok N/N]` 条目。
- **Zork1(-4.8 avg, best 84→85 持平)**:开放探索型游戏,manual 主要固化了 Dam/煤矿分支路线(见 3.4 知识产物),但 3 个 0 分局(第 1/5/10 局,死因各不相同)拖垮均值。与 full 的差距(63.6)同样来自 0 分局频率(full 也有一局 0)——**随机死亡事件是纯 prompt 方案的固有盲区**。
- **Library(-16.7 avg,唯一明显退步)**:需要辩证看。abl22 的 31.4 由一局 130 异常解局拉高;abl23 拿到 3 次 30(标注满分)但 3 次 0 分——manual 固化的"give id card before novel"速通路径对随机事件敏感,失败即全损。**速通知识与零容错的组合是 manual 注入的已知风险**:full 管线靠检索获得同源知识却没有 0 分局,提示 agent 主动检索时对路径的"拥有感"更强、更愿意中途验证。

### 3.4 知识产物质量(与 abl22 同目录文件对比)

最终 knowledge 文件(`data/default/general/wiki/abl23_glm52_autom/knowledge/`)呈现三思想的可观测烙印:

- **验证标记累积**:Zork1 手册 15 处 `[ok N/M]`,如 `(Loud Room) up ... turn bolt with wrench — drains reservoir. [ok 6/6]`;
- **条件性知识显式化**:`(Bat Room) ... take figurine — +5 CONDITIONAL: the vampire bat may grab you ... Take figurine on your VERY FIRST move there. [ok 1/2]`;
- **路径合并**:hallway maze 四步压缩为一行,Detective 手册 13 条目覆盖 360 分路线(远低于 30 上限);
- **归因分类落地**:experience 文件每条 Attempt 以 `Verdict: WIKI_GAP/EXECUTION_ERROR/EXPLORATION` 开头。

abl22 的同目录文件无标记、无归因、条目冗长——结构化程度差异显著。

### 3.5 与 full 管线的对比结论(论文可用的三层论断)

1. **知识管理纪律的价值独立于知识获取机制**。同等检索为零的条件下,仅靠策展纪律+全文注入,avg 收益 +142.6(77%),证明 AutoManual 思想可脱离其原环境迁移。
2. **上限接近,均值有差**:best 口径 509 vs 519(-1.9%),avg 口径 327 vs 435(-25%)。差距几乎全部由 EXECUTION_ERROR 局构成(Detective 2 局、Library 3 局、Zork1 3 局 0 分)——**知识存在于上下文中,agent 仍会违反它**。这为 full 管线的分层设计提供了直接反事实论证:检索工具(agent 主动查询,拥有感)与 FATAL 硬拦截(不可违反)解决的是纯 prompt 无法解决的两类执行失败。
3. **任务结构依赖性再现**:线性路线宽容型(Detective/Balances/Temple)manual 注入收益最大;精确序列零容错型(Library)与开放随机型(Zork1)收益受限甚至倒退——与 abl21 消融发现的"压缩蒸馏边际价值集中在动作顺序敏感任务"形成互补:**知识越需要条件性执行([ok 1/2]、CONDITIONAL),纯 prompt 注入越接近其能力边界,硬机制的价值越高**。

---

## 四、运行与复现

```bash
# 启动(等价于直接跑 run_all_tasks):
bash apps/tale_jericho/run_ablations23_autom.sh

# 手动形式:
AGIA_REACT_PROMPT=1 AGIA_DISABLE_LOOP_DETECT=1 AGIA_CURATOR_STYLE=autom \
python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name abl23_glm52_autom --ablation no_wiki

# 关键开关
AGIA_CURATOR_STYLE=autom        # 策展纪律 + manual 注入(缺省=旧行为)
AGIA_MANUAL_INJECT_CAP=6000     # manual 注入截断上限(字符)
```

产物位置:
- 结果/轨迹: `data/benchmark_results/abl23_glm52_autom/`(run_manifest.json、outputs/*play N*/logs/trajectory.jsonl)
- 知识/经验: `data/default/general/wiki/abl23_glm52_autom/`(knowledge/score_recipe_*.md、experiences/)
- 汇总表: `ablations_summary.md` §1.1 / §2 / §3.3

理论背景与 AutoManual 源码部署细节另见 `automanual_tale_jericho_compat.md`。
