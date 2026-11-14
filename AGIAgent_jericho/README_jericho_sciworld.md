# AGIAgent_jericho 工程交接文档(Jericho 消融实验全量指南)

> 最后更新: 2026-11-14 | 交接人: 前序智能体会话
> 本文档是接手本工程的必读手册: 如何启动消融、数据在哪、怎么分析、有哪些坑。

---

## 1. 工程布局与两套目录

| 目录 | 角色 | API key | 用途 |
|---|---|---|---|
| `~/AGIAgent_jericho`(主目录) | 主实验场 | `config/config.txt` + `apps/tale_jericho/config.txt` 里的 key(官方 coding 端点, 请求 glm-5.2 实际返回 glm-5.3) | 大部分消融 |
| `/mnt/data/20260917/AGIAgent_jericho`(副本) | 并行实验场 | 独立 key(`f27751ea…`) | abl41/43/45 在此跑, 与主目录错峰 |

**注意**: 主目录的 `data/` 是指向 `/mnt/data/AGIAgent_jericho_data` 的**软链**(根盘曾满, 2026-09-25 迁移), 所有 benchmark_results 实际存储在 /mnt/data。`ls ~/AGIAgent_jericho/data/benchmark_results/` 正常工作。

其他关联目录:
- `/mnt/data/EvoTest`: EvoTest 官方 scaffold + 我们的复现(output/logs; backup_20260923/ 与 backup_thinkingoff_r2/ 与 backup_thinking_on/ 是三轮跑的原件备份)
- `~/RecMem`: RecMem 官方包 + 自写适配器 `recmem_jericho.py` + 三个 run 的日志(abl24_*.out / abl41r_*.out / abl41r2_*.out)与 Qdrant stores(~/recmem_* 已软链到 /mnt/data/recmem_stores)
- `/mnt/data/AGIAgent_scienceworld_glm52`: ScienceWorld 消融(config 已切回老官方 key; 两臂 n=3 实验见 §5.1)
- `/mnt/data/brain-inspired-agent-iclr-2027`: 论文仓库(独立 git, remote=(private paper repo))

## 2. 统一实验协议(六游戏面板)

```
游戏: --task-list "[13,24,51,53,8,44]"
  = Detective(max 360) / Library(30) / Zork1(350) / Zork3(7) / Balances(51) / Temple(44=Temple, max 35)
迭代: --max-iterations 10 (10 局/游戏)
步数: --play-loops 110 (每局最多 110 轮)
策展: --phase-m-loops 30 (局间 curator 会话)
并行: --parallel-tasks 6 (同 key 建议 ≤8 并发, 更多会 429)
模型: config.txt 的 model=glm-5.2 (coding 端点实际服务 glm-5.3, 论文已统一改称 GLM-5.3)
工具协议: Tool_calling_format=True (两处 config 都必须是 True! False=chat-based, 有空转 bug, 见 §7)
```

归一化口径(论文标准): 每局 `play_best_score ÷ 游戏max × 100`, 跨 6 游戏平均; **Mean**=全部 10 局均值, **Final**=仅第 10 局。

## 3. 如何启动一个消融实验

### 3.1 标准启动模板

```bash
cd ~/AGIAgent_jericho
export TALES_CACHE_HOME=/mnt/data/tales_cache    # 游戏 rom 缓存(必须)
export TALE_SUITE_ROOT=~/tale-suite # tales 环境(副本目录跑时必须, 主目录同源可不设)
# ↓↓ 按消融类型加开关(见 §4) ↓↓
setsid nohup python3 apps/tale_jericho/run_all_tasks.py \
  --task-list "[13,24,51,53,8,44]" \
  --play-loops 110 --phase-m-loops 30 \
  --max-iterations 10 --parallel-tasks 6 \
  --experiment-name ablXX_描述 \
  [--ablation 模式名] \
  > nohup_ablXX.out 2>&1 < /dev/null &
```

**最省事的方式**: 复制一个现有的 `apps/tale_jericho/run_ablationsNN_*.sh` 改实验名。历史脚本全部保留, 每个都是可运行样板。

### 3.2 消融开关速查(全部环境变量/参数)

| 消融 | 开关 | curator 写什么 | agent 读什么 |
|---|---|---|---|
| full(程序预抽取) | (无, 默认) | 程序摘要→LLM 合成 gist + 语义页 | knowledge+experiences 检索 + FATAL 门 |
| **主方案 E5(LLM 直读)** | `AGIA_CURATOR_NO_PREEXTRACT=1` | LLM 直读原始 trajectory.jsonl(提示词含抽取方法)写 gist + 语义页 | 同上 |
| −语义页(检索只剩 experiences) | `--ablation no_knowledge` | 照常写, 但 knowledge 查询被禁 | 仅 experiences; 门失效(门依赖 knowledge 条目) |
| −门(仅关硬拦截) | `--ablation no_fatal_guard` | 照常 | 检索照常; `_check_fatal_action` 预执行拦截关闭(FATAL 条目仍可读) |
| 底座(无跨局记忆) | `--ablation no_wiki` | 无 | 无 wiki_memory_read(仅局内 30 步滑窗) |
| E1 散点 | `AGIA_CURATOR_REPRESENTATION=scatter` | (房间,命令,Δ) 无序三元组; 无叙事/无语义页 | 仅散点检索 |
| E2 去时序 | `AGIA_CURATOR_NO_TIME=1` + `AGIA_SHUFFLE_WIKI=1` | 独立事实 bullet(无顺序) | 检索命中页等权乱序(相似度信号清零) |
| E6 纯实录 | `AGIA_CURATOR_PURE_EPISODIC=1` + `--ablation no_knowledge` | [step K]动作@房间→"游戏原文引语"(禁因果/规则/结论) | 仅事件流 |
| AutoManual 式 | `AGIA_REACT_PROMPT=1` + `AGIA_DISABLE_LOOP_DETECT=1` + `AGIA_CURATOR_STYLE=autom` + `--ablation no_wiki` | 30 条目手册(失败归因+[ok N/M]) | manual 全文注入 prompt(manual-as-context) |

开关实现位置: `apps/tale_jericho/run_all_tasks.py` 的 `_phase_m_requirement()`(curator 侧)与 `src/wiki_memory.py`(检索/禁用侧)。开关可叠加但从未组合测试过, 单变量原则。

### 3.3 接力启动(等前一个实验结束再自动开跑)

模板: `apps/tale_jericho/launch_abl42_scatter.sh`(轮询 pending=0 + 前置自检 + setsid 启动)。
**坑**: 自检里判断"无残留 agia.py"必须只 pgrep 本目录的实验名(全局 pgrep 会把另一个目录的并行实验误算成残留, 导致 launcher 自杀——abl39 launcher 曾因此中止)。

### 3.4 断点续跑(实验中断后)

`run_all_tasks.py` 自带 `--resume`(默认开): 读取已有 `phase_records.json`, 跳过已完成的局, 只补 pending 的。
坏局清洗法(如 429 烧完轮次的零动作局, abl47 案例):
```python
# 判据: status=='max_rounds_reached' 且 best_score is None 且该局 trajectory actions==0
# 把这些局 play_status 改回 'pending', 删掉对应 output_*_playN_* 目录, 再用同名 --resume 启动
```
**切勿**把真实死亡的 0 分局当坏局(它们有完整 trajectory, actions>0)。

## 4. 数据在哪 & 如何读取

### 4.1 每个实验的产出

```
data/benchmark_results/<experiment_name>/
├── run_manifest.json          # 配置快照(并行数/任务表/时间戳)
├── outputs/
│   ├── output_*phase_records.json   # ★ 逐局分数主数据: [{play_status, play_best_score, ...} × 10]
│   ├── output_*playN_*/logs/
│   │   ├── manager.log        # 轮次/输入输出token/429(分析空转与成本用)
│   │   ├── manager.out        # 模型侧流(每轮 💬)
│   │   └── trajectory.jsonl   # ★ 每步动作+观察+分数(curator 的输入, 也是复算一切的数据源)
│   └── output_*phasemN_*/     # 局间策展会话
└── (wiki 在别处, 见 4.2)
```

### 4.2 记忆文件(wiki)

```
data/default/general/wiki/<experiment_name>/
├── knowledge/score_recipe_<game>.md    # 语义页(≤800词, FATAL 条目, Evidence 链接)
├── experiences/<日期>/<game>.md        # gist 档案(append-only, 检索整页注入)
└── .wiki_index.npz                     # embedding 索引缓存(增量更新)
```

### 4.3 标准分析命令(背下来)

```bash
# 进度检查(最常用)
python3 -c "
import json, glob
for p in sorted(glob.glob('~/AGIAgent_jericho/data/benchmark_results/ablXX_*/outputs/*phase_records.json'.replace('~','~'))):
    game = p.split('_Jericho')[1].split('_')[0].replace('Env','')
    recs = json.load(open(p))
    done = [r for r in recs if r.get('play_status') not in (None,'pending')]
    print(game, len(done), '/10', [int(r.get('play_best_score') or 0) for r in done])"

# 均值/最终值/最高分计算
python3 -c "
import json, glob, statistics
G = ['Detective','Library','Zork1','Zork3','Balances','Temple']
M = {'Detective':360,'Library':30,'Zork1':350,'Zork3':7,'Balances':51,'Temple':35}
def seqs(e):
    out = {}
    for p in glob.glob(f'~/AGIAgent_jericho/data/benchmark_results/{e}/outputs/*phase_records.json'):
        n = p.split('/')[-1]; i = n.find('JerichoEnv')+11
        out[n[i:n.find('_phase_records')]] = [r.get('play_best_score') or 0 for r in json.load(open(p)) if r.get('play_status') not in (None,'pending')]
    return out
r = seqs('ablXX_...')
print('Mean', statistics.mean([statistics.mean(r[g])/M[g]*100 for g in G]))
print('Final', statistics.mean([r[g][-1]/M[g]*100 for g in G]))
print('best', sum(max(r[g]) for g in G))"

# 空转/错误体检(429 是否成灾)
for f in ~/AGIAgent_jericho/data/benchmark_results/ablXX_*/outputs/output_*play*/logs/manager.log; do
  echo "$f: $(grep -c '429' $f) 429s"; done
# 判定坏局: 含错会话的 trajectory actions 数(0=坏局, >0=瞬态已恢复)

# token 成本统计(论文 §compute cost 的来源)
python3 -c "
import glob, re
inp = out = 0
for p in glob.glob('.../output_*play*/logs/manager.log'):
    for m in re.finditer(r'Input: (\d+), Output: (\d+)', open(p, errors='ignore').read()):
        inp += int(m.group(1)); out += int(m.group(2))
print(f'{inp/1e6:.1f}M in / {out/1e6:.1f}M out')"
```

## 5. 外部基线的启动方式(与主框架不同!)

| 基线 | 启动 | 说明 |
|---|---|---|
| **RecMem** | `bash ~/RecMem/run_abl41r2_recmem_2par.sh`(或直接对每游戏跑 `~/RecMem/.venv/bin/python ~/RecMem/recmem_jericho.py --game JerichoEnvX --steps 110 --episodes 10 --stores ~/recmem_<name>`) | key 走 env `ZHIPU_API_KEY`(chat)与 `ZHIPU_EMBED_API_KEY`(embedding, 可不同 key); 官方核心勿改 |
| **EvoTest** | `cd /mnt/data/EvoTest && GLM_DISABLE_THINKING=1 RUNS=10 STEPS=110 AGENT=our GAMES="detective library zork1 zork3 balances temple" setsid nohup bash run_glm_6games.sh &` | thinking 开关=`GLM_DISABLE_THINKING=0/1`; 单游戏串行(API 并发1); 每游戏完成写 output/<game>/our/glm-5.2/<stamp>/evaluation_summary_*.json; **重跑前必须备份/清空 output/**(历史三轮原件在 backup_* 目录) |
| **AutoManual 式** | 主框架模板 `run_ablations50_autom_native.sh` | 见 §3.2 开关行 |

### 5.1 ScienceWorld 实验(63 困难任务, 有/无记忆两臂 n=3)

工程目录: `/mnt/data/AGIAgent_scienceworld_glm52`(config=老官方 key, 并行≤8; 两臂同时跑时**各 3 并发**)

任务集: 63 行号清单(211 对面板中 att1<100 的困难子集), 完整清单见任一实验的 run_manifest.json `task_list` 字段。

**有记忆臂(iterative 模式, 5 局 won-skip)**:
```bash
cd /mnt/data/AGIAgent_scienceworld_glm52
export TALES_CACHE_HOME=/mnt/data/tales_cache TALE_SUITE_ROOT=~/tale-suite
setsid nohup python3 apps/scienceworld/run_all_tasks.py \
  --selection-mode fixed_total --fixed-dataset-split test \
  --task-list "$(python3 -c "import json;print(json.load(open('data/benchmark_results/sw_63_iterative_r1/run_manifest.json'))['task_list'])")" \
  --play-loops 100 --phase-m-loops 15 --max-iterations 5 --parallel-tasks 3 \
  --experiment-name sw_63_iterative_rN \
  > nohup_sw63_iter_rN.out 2>&1 < /dev/null &
```

**无记忆臂(baseline 链式 5 局)**: `run_nomem2_full_chain.sh` / `run_nomem3_full_chain.sh` 为模板(第1局全量63, 之后每局只跑上局未满分任务, 自动收缩 task-list; 第一条链 r1 = `run_nomem_rounds345.sh`, 复用更早的 `sw_glm52_63_nomem` 当首局)。

**统计口径(与 Jericho 不同!)**:
- 主指标 = score_rate(0~1, score_summary.json), 非原始分;
- **won-skip 陷阱**: skipped 局 `play_best_score=None`, 直接 `or 0` 会造假下滑曲线; 正确口径 = 存活任务逐局均值 / 本局新解(score_rate==1.0) / 跨局累计 best;
- 分析脚本与全部终值见 `~/AGIAgent_jericho/experiment_notes/scienceworld_memory_vs_nomemory.md`(n=3 定稿)。

## 6. 常用分析产出文档(写作时直接引用)

| 文档 | 内容 |
|---|---|
| `~/AGIAgent_jericho/experiment_notes/ablations_final_summary.md` | ★ 终版汇总: 配置总表 + 分数列表 + 最终分析(先读这个) |
| `~/AGIAgent_jericho/experiment_notes/ablations_detailed_scores.md` | 全部实验逐局明细(110+ 节, 含历史弃用标记; **末两节 = A2 建议质量审计 + A3 成本审计, 2026-11-14 定稿**) |
| `~/AGIAgent_jericho/experiment_notes/scienceworld_memory_vs_nomemory.md` | ★ SW 有/无记忆两臂 n=3 对照(设计+终值+可复现) |
| `~/AGIAgent_jericho/experiment_notes/mechanism_comparison.md` | 竞品代码级解剖(EvoTest 散点/RecMem 原子事实) + 创新点提炼 + 已证伪机制 |
| `~/AGIAgent_jericho/experiment_notes/semanticization_ladder.md` | gist 理论(verbatim/gist/语义三层)与语义化阶梯 |
| `~/AGIAgent_jericho/experiment_notes/ablations_summary_table.csv` | 全部实验一行一总结(CSV) |
| 论文仓库 `docs/` + `data/derived/` | 论文表格 CSV 源 + `plot_learning_curves.py` 等图脚本 |


## 6.1 审计脚本(`scripts/`, 支撑论文附录 A2/A3)

| 脚本 | 审计什么 | 输出对应 |
|---|---|---|
| `scripts/audit_advice_quality.py` | **建议质量审计(A2)**: 三个主方案跑(abl41/45/47)知识页全部条目逐条分类(verified/partial/unverified/contradicted; 词条级证据链核对+分数主张与 phase_records 交叉验证), 以及 180 次尝试的检索率与 38 次死亡的"是否违反完整警告"裁定(`--adjudicate` 开死亡部分) | 463 条: 371 verified(80%) / 64 partial(14%) / 28 unverified(6%) / 0 contradicted; 死亡 0 次违反完整警告, ≥30 次为首次遭遇 → 论文附录表 tab:advice-audit |
| `scripts/audit_token_costs.py` | **Token/策展成本审计(A3)**: 汇总 react(abl22)/gist-only(abl46/48/49)/BISE(abl41/45/47) 每条件全部 play+phasem 的 manager.log token 用量 | ReAct 1.22M / gist-only 1.88M / BISE 1.64M tok/attempt; 策展占比 8%; 记忆上下文增长 +11%/+52%/+38% → 论文附录表 tab:costs |

数据依赖: 两个脚本读 `data/benchmark_results/`(phase_records + manager.log + trajectory)与 `data/default/general/wiki/`(知识页+gist), 全部包含在发布包 `jericho_results_core.tar.gz` + `wiki_memory_jericho.tar.gz` 中(React 条件在 `jericho_results_deprecated.tar.gz` 的 abl22)。数据根默认取脚本所在仓库的 `../data`(按 README.md 还原), 亦可用 `AGIA_DATA_ROOT` 环境变量指向任意解压位置:
```bash
AGIA_DATA_ROOT=/path/to/AGIAgent_jericho_data python3 scripts/audit_advice_quality.py
```
数字落点: `experiment_notes/ablations_detailed_scores.md` 末两节(2026-11-14 定稿)与论文附录 A2/A3; 条目与 rebuttal W2-b/W2-c 对应。

## 7. 历史坑与关键教训(必读)

1. **chat-based 空转 bug(已解决, 勿回退)**: `Tool_calling_format=False` 时 GLM 在消息体里写 `<invoke>` XML, 2026-08-04 起服务端退化导致模型只输出意图文本不输出工具调用, 每局浪费 18-31 轮。修复=两处 config 都设 `True`(native tool calling)。chat 期 13 个 run 已弃用(明细文档有总表), 引用需注明。
2. **coding 端点静默升级**: 请求 glm-5.2 实际返回 glm-5.3(2026-09-24 发现, 回溯不可考)。论文已全局改称 GLM-5.3。验证法: curl 后看响应 `model` 字段。
3. **429 的两种形态**: 瞬态(重试吸收, 含错会话 actions>0 即无害) vs 灾难(重试烧完 110 轮, actions=0, 局作废需 resume 修补)。判定看 trajectory actions 数, 不看 429 计数。
4. **限流并发**: 官方 key 同 key 并发 ≤8 安全(每会话偶发 1-2 次 429 正常); 10 并发会灾难化。两目录用不同 key 可并行。中转 key(app2.heyenewapi.cc.cd)限 10 req/min, 只能 1-2 并发。
5. **副本目录跑 jericho 必须** `export TALE_SUITE_ROOT=~/tale-suite`(代码按相对路径找 tale-suite, 副本位置找不到; abl40 曾因此秒挂)。
6. **根盘容量**: `/`只有 49G, Qdrant/大数据务必放 /mnt/data(data/ 已软链, RecMem stores 已软链)。
7. **单跑结论不可信**: E7 单跑(52.0)曾制造"+4.6 语义页交互"假象, n=3 后归零。任何组件级结论需 n≥2; ep1 冷启动方差 ±7.9。
8. **max_rounds ≠ 坏局**: 跑满 110 轮是正常现象(探索型), 只有 actions=0 才是坏局。
9. **副本文件名差异**: 副本目录 phase_records 文件名与主目录 regex 略有差异, 分析脚本用 `n.find('JerichoEnv')+11` 到 `'_phase_records'` 切片最稳。

## 8. 当前状态快照(2026-11-14)

- **全部收官, 无进行中实验**: 主方案 E5 n=3=55.7±2.1; E7 n=3=55.0±2.7; full n=2=53.2±1.2; −语义 n=2=53.5; −门 n=2=53.2; ladder 三臂 n=3(E6 纯实录 51.2±1.9 / E1 散点 44.2±4.9 / E2 去时序 51.9±3.3); 底座 33.6; EvoTest 关思考 n=3=37.7±2.6(+开思考 n=1=28.8); RecMem n=3=33.4±1.8; AutoManual n=1=53.0; 主方案 N=50(abl59): Mean 64.8 / Final 69.0
- **ScienceWorld 两臂 n=3 定稿**: 有记忆 92.2±0.4(满分53.3/63) vs 无记忆 85.2±0.2(41.7/63), 净效应 +7.0pp/+11.7 任务; 首次重试局新解 14.3 vs 8.0(×1.8); 论文 44.4→70.0 的 +25.7 中约 2/3 为选择偏差+best-of-k
- **打包副本**: /mnt/data/AGIAgent_ICLR2017(两工程 1.4G, 已剔除 nohup 控制台日志/__pycache__/无关 apps)
- **论文**: /mnt/data/brain-inspired-agent-iclr-2027, 已含全部终值; 编译命令: 主稿 `pdflatex main.tex`(两遍); 中文 `export PATH=$HOME/bin:$PATH TEXMFHOME=$HOME/texmf && xelatex main_zh.tex`(两遍; bbl 需 bibtex main_zh 重建); SW 节待按 n=3 结果改写
- 机器: 8 核/15G, 双 key(官方 coding + 中转已失效), tales_cache 共享只读
