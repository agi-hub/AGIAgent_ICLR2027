# scienceworld

Native ScienceWorld app for `AGIAgent_v3`.

详细交接说明见 [HANDOFF.md](/Users/manykun/Documents/master/AGIAgent/AGIAgent_v3/apps/scienceworld/HANDOFF.md)。

## Run One Session

```bash
cd /path/to/AGIAgent_v3
python agia.py --app scienceworld
```

## Run Benchmark

默认使用固定数据集切片模式 `fixed_total`。当前主用法是按 `valid` / `test` 固定样本集切片，而不是运行时任务顺序。

```bash
cd /path/to/AGIAgent_v3

# valid 前 10 个样本
python apps/scienceworld/run_all_tasks.py \
  --selection-mode fixed_total \
  --fixed-dataset-split valid \
  --task-count 10 \
  --parallel-tasks 2 \
  --experiment-name scienceworld_valid_top10

# 完整 valid
python apps/scienceworld/run_all_tasks.py \
  --selection-mode fixed_total \
  --fixed-dataset-split valid \
  --parallel-tasks 2 \
  --experiment-name scienceworld_valid_full
```

说明：
- `phase1_explore` 默认 `200` 轮
- `phase2_solve` 默认 `100` 轮
- benchmark 输出在 `data/benchmark_results/<experiment_name>/`
- 长日志在 `data/default/general/experience/<experiment_name>/logs/`

## Test

```bash
python -m unittest tests.test_scienceworld_entry
```

## Implementation Overview

当前 ScienceWorld 的实现主链如下：

- `apps/scienceworld/run_all_tasks.py`
  - 负责 benchmark 任务切片、phase1/phase2 拆分、子进程启动、结果汇总
- `agia.py`
  - 通用 agent 入口，按 `--app scienceworld` 加载 prompt、config 和工具
- `src/tool_executor.py`
  - 负责工具注册、phase1/phase2 memory query gating、BIAgent query 接入
- `src/tools/scienceworld_tools.py`
  - 对原生 `ScienceWorldEnv` 的封装，向 agent 暴露 `scienceworld_action`
- `src/biagent/`
  - `scene.py`：将环境交互整理为 scene
  - `pipeline.py`：处理 `trigger_curiosity`，驱动 scene/reflection/graph 写入
  - `retrieval.py`：phase2 检索 world model / skill graph
  - `reflection.py`、`world_graph.py`、`skill_graph.py`：长期资产生成与更新

当前 memory 目录组织方式与 TextQuests 一致：

```text
data/default/general/biagent_memory/<experiment_name>/scienceworld/<env_name>/
```

详细实现说明见 [HANDOFF.md](/Users/manykun/Documents/master/AGIAgent/AGIAgent_v3/apps/scienceworld/HANDOFF.md)。

## Server Benchmark Result

当前仓库中保留了一份服务器跑出的完整 `valid` 结果镜像：

- [benchmark_summary.json](/Users/manykun/Documents/master/AGIAgent/AGIAgent_v3/server_snapshots/scienceworld/scienceworld_valid_full_varscope_v1/benchmark_summary.json)
- [run_manifest.json](/Users/manykun/Documents/master/AGIAgent/AGIAgent_v3/server_snapshots/scienceworld/scienceworld_valid_full_varscope_v1/run_manifest.json)

核心指标：
- `task_total = 194`
- `won_count = 130`
- `win_rate = 67.01%`
- `avg_score_rate = 0.8053`
- `max_rounds_reached_count = 44`
- `error_count = 0`

说明：
- 这份结果文件中的 `results_json` / `run_root` 指向 `/root/BIAgent/...`
- 因此它应视为“服务器实验结果导回后的本地镜像”，不是纯本地直接跑出的 benchmark
- 当前仓库里这份镜像已整理到 `server_snapshots/scienceworld/scienceworld_valid_full_varscope_v1/`

## Tool Exposed To Agent

- `scienceworld_action`
- `trigger_curiosity`
