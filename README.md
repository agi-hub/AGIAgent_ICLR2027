# AGIAgent_ICLR2027 Packaging Guide | 打包说明 (Code / Data / Archives)
# AGIAgent_ICLR2027 打包说明(代码 / 数据 / 压缩包 三层)

> Date 日期: 2026-11-14 | Paper 论文: brain-inspired-agent (ICLR 2027 submission 投稿)
> Contains all ablation experiment code & data (n=3 finalized) for Jericho + ScienceWorld.
> 本包包含 Jericho + ScienceWorld 全部消融实验的代码与数据(n=3 定稿)

## Archives (ready for distribution) 压缩包(可直接分发)
## `/mnt/data/AGIAgent_ICLR2027_archives/` (624M)

| Archive 压缩包 | Size 大小 | Contents 内容 | score_summary |
|---|---|---|---|
| `jericho_results_core.tar.gz` | 244M | **26 core experiments 核心实验**: E5 main n=3 (abl41/45/47), E7 n=3 (46/48/49), ladder arms n=3 (scatter 散点 42/54/57, no-time 去时序 43/55/58, pure-episodic 纯实录 44/53/56), full n=2 (34/35), −semantic −语义 n=2 (38/39), −guard −门 n=2 (36/37), no-memory base 底座 (19_no_wiki), AutoManual (50/51/52), N=50 long-run 长程 (59) | 3508 |
| `jericho_results_deprecated.tar.gz` | 244M | 41 deprecated chat-era / early runs 弃用与早期跑 (abl7-33 etc.; basis of paper Table 2 deprecation 论文表2弃用口径依据) | 5092 |
| `scienceworld_results.tar.gz` | 108M | All 20 SW experiments 全部实验: 211-pair source run (test_full), iterative r1-3 (memory arm 有记忆臂), no-memory chains ×3 (nomem/nomem2/nomem3), v2 partial run | 1833 |
| `wiki_memory_jericho.tar.gz` | 3.7M | Wiki memory for 87 Jericho experiments (semantic pages score_recipe_*.md + gist experiences/) 语义页+gist 档案 | — |
| `wiki_memory_scienceworld.tar.gz` | 0.3M | Wiki memory for 7 SW experiments | — |
| `extras.tar.gz` | 24M | long_term_memory (early memory data 早期记忆数据) + reference_papers (PDFs 参考 PDF) | — |

score_summary total 合计 10433, consistent with the data package 与数据包全量一致. Jericho archives extract to experiment directories directly (subdirs of benchmark_results); the SW archive extracts to a `benchmark_results/` directory. Jericho 包顶层即实验目录, SW 包顶层是 benchmark_results/。

## Directory Layout 目录结构

```
/mnt/data/AGIAgent_ICLR2027/            # code package 代码包 (18M, no experiment data 无实验数据)
├── AGIAgent_jericho/                   # Jericho main project 主工程 (code + analysis docs)
│   ├── src/ apps/ prompts/ config/     # code & prompts 代码与提示词
│   ├── experiment_notes/               # analysis outputs 分析产出 (summaries/details/figures)
│   └── README_jericho_sciworld.md      # ★ ops manual 运行手册 (incl. SW §5.1)
└── AGIAgent_scienceworld_glm52/        # ScienceWorld project (code + chain scripts 链式脚本)

/mnt/data/AGIAgent_ICLR2027_data/       # data package 数据包 (3.9G, mirrors code package 镜像对应)
├── AGIAgent_jericho_data/
│   ├── benchmark_results/              # 67 experiments × (phase_records + trajectory + score_summary)
│   ├── default/general/wiki/           # wiki memory, 87 experiments 语义页+gist
│   ├── long_term_memory/               # early-era memory data (embedding/texts caches)
│   └── reference_papers/               # reference PDFs (原 papers/)
└── AGIAgent_scienceworld_glm52_data/
    ├── benchmark_results/              # 20 SW experiments (211 source / iterative r1-3 / nomem chains)
    └── default/general/wiki/           # SW wiki memory
```

## Restoring Data into the Code Folder 如何把数据还原到主代码文件夹

**Option 1 (move/copy for a standalone runnable project) 方法一(移动/拷贝)**:

```bash
# Jericho: put data back as data/
mv  /mnt/data/AGIAgent_ICLR2027_data/AGIAgent_jericho_data \
    /mnt/data/AGIAgent_ICLR2027/AGIAgent_jericho/data
# ScienceWorld: same 同理
mv  /mnt/data/AGIAgent_ICLR2027_data/AGIAgent_scienceworld_glm52_data \
    /mnt/data/AGIAgent_ICLR2027/AGIAgent_scienceworld_glm52/data
```

Two items originally lived at the **project root** (not inside data/) 另有两项原在工程根目录:
```bash
mv /mnt/data/AGIAgent_ICLR2027_data/AGIAgent_jericho_data/long_term_memory \
   /mnt/data/AGIAgent_ICLR2027/AGIAgent_jericho/
mv /mnt/data/AGIAgent_ICLR2027_data/AGIAgent_jericho_data/reference_papers \
   /mnt/data/AGIAgent_ICLR2027/AGIAgent_jericho/papers
```
(Not required for reproducing experiments 这两项不影响实验复现, 可不还原)

(To keep the data package intact, replace `mv` with `cp -a` (+3.9G). 若想保留数据包原样, 把 mv 换成 cp -a, 多占 3.9G)

**Option 2 (symlink, no extra space; matches the original setup) 方法二(软链)**:

```bash
ln -s /mnt/data/AGIAgent_ICLR2027_data/AGIAgent_jericho_data \
      /mnt/data/AGIAgent_ICLR2027/AGIAgent_jericho/data
ln -s /mnt/data/AGIAgent_ICLR2027_data/AGIAgent_scienceworld_glm52_data \
      /mnt/data/AGIAgent_ICLR2027/AGIAgent_scienceworld_glm52/data
```

After restoring, launch experiments via the template in `AGIAgent_jericho/README_jericho_sciworld.md` §3.1
(dependencies: `TALES_CACHE_HOME` game cache, `TALE_SUITE_ROOT` tale-suite, API key in `apps/*/config.txt`).
还原后按运行手册 §3.1 模板启动实验(依赖: TALES_CACHE_HOME 游戏缓存、TALE_SUITE_ROOT、apps/*/config.txt 的 API key)。

## Integrity Check Values (self-check after restore) 完整性校验值(还原后自查)

| Item 项 | Expected 期望值 |
|---|---|
| Jericho benchmark_results experiment dirs 实验目录 | 67 (incl. abl53/56 merged from the 20260917 copy 含副本并入) |
| Jericho score_summary.json total | 8600 |
| SW benchmark_results experiment dirs | 20 |
| SW score_summary.json total | 1833 |
| phase_records.json | 416 (Jericho) + 416 (SW) |

## Key Documents (inside the code package) 关键文档索引(代码包内)

- `AGIAgent_jericho/README_jericho_sciworld.md` — ★ Ops manual 运行手册: protocols / ablation switches / analysis commands / pitfalls / SW §5.1
- `AGIAgent_jericho/experiment_notes/ablations_final_summary.md` — Final summary (read first 终版汇总, 先读)
- `AGIAgent_jericho/experiment_notes/ablations_detailed_scores.md` — Per-episode details; last two sections = the finalized A2/A3 audits 逐局明细(末两节为 A2/A3 审计定稿)
- `AGIAgent_jericho/experiment_notes/ablations_summary_table.csv` — One row per experiment, 51 rows 一行一实验

### Audit scripts 审计脚本

`AGIAgent_jericho/scripts/` contains the two audit scripts backing appendix tables A2/A3 (usage, data dependencies and expected outputs: see ops manual §6.1):
`AGIAgent_jericho/scripts/` 内含支撑论文附录表 A2/A3 的两个审计脚本(用法、数据依赖与期望输出见运行手册 §6.1):
- `audit_advice_quality.py` — advice-quality audit: classifies all 463 schema-page entries (80% verified / 14% partial / 6% unverified / 0 contradicted) and adjudicates the 38 logged deaths (0 violated a complete warning). 建议质量审计(463 条分类 + 38 次死亡裁定)。
- `audit_token_costs.py` — token/curation cost audit: ReAct 1.22M / gist-only 1.88M / BISE 1.64M tok per attempt, curation share 8%. Token/策展成本审计。
Both read only data shipped in the release archives; data root defaults to `<repo>/data` or override via `AGIA_DATA_ROOT`. 输入全部来自发布包; 数据根默认仓库 data/, 可用 AGIA_DATA_ROOT 覆盖。

## Removed Content (do not look for these) 已剔除内容(勿找)

nohup console logs, `experiment_logs_nohup/`, `data/default/general/experience/` runner logs,
`__pycache__`, legacy product scaffolding (GUI/jupyter_demo/routine etc.), unrelated apps
(childedu/colordoc/patent/tale_alfworld/tale_textworld/textquests). None affect experiment data;
all experiment data lives in benchmark_results. 以上均与实验数据无关, 数据本体全在 benchmark_results。
