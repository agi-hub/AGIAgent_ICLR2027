# ScienceWorld 批量运行防卡死机制 —— 跨版本同步指南

本仓库的批量运行器（`run_all_tasks.py`）已经解决过"运行期间子进程无限卡死"的问题。本文档梳理该机制的关键改动点，供你在**另一版本代码**上同步移植。所有改动围绕一个核心契约：**子进程心跳 ↔ 运行器看门狗**。

---

## 0. 问题背景

批量运行时，每个 task/phase 都 `fork` 一个独立 `agia.py` 子进程。卡死来源有三类：

| 卡死类型 | 表象 | 根因 |
|---|---|---|
| 模型 API 死循环 | 子进程不退出，CPU 空转 | LLM 返回空内容/陷入无意义重试，永不 `done=true` |
| 模型服务故障 | 子进程阻塞在 API 调用 | 上游 ngrok 隧道掉线 / 502 / 404，重试耗尽后挂起 |
| 信号中断 | 子进程半死 | SIGTERM/SIGKILL 被吞、`subprocess.Popen` 不返回 |

旧版本对此无任何处理 → 一个卡死的子进程会**永久占用一个并行槽**，批次整体进度停滞。新版本通过「心跳文件 + 看门狗 + 分类重试」三段式解决。

---

## 1. 核心架构：心跳契约

```
┌─────────────────────┐  每轮写入  ┌───────────────────────────┐
│   agia.py 子进程    │ ─────────> │ .agia_spawn_manager_status│
│ (src/ executor)     │            │       .json               │
└─────────────────────┘            └─────────────┬─────────────┘
                                                 │ 运行器每 1s 读取
┌─────────────────────────────────────────────────▼─────────────┐
│              run_all_tasks.py  PhaseRunner (看门狗)            │
│  - 读心跳 → 判断是否 stale (>1800s 无更新)                      │
│  - stale → SIGTERM(20s宽限) → SIGKILL → 标记 terminal → 重试   │
└────────────────────────────────────────────────────────────────┘
```

**关键**：心跳文件 `.agia_spawn_manager_status.json` 是两个进程唯一的通信媒介。**两边都必须实现**，否则看门狗要么误杀（子进程没写心跳）、要么无效（运行器不读）。

---

## 2. 子进程侧改动（src/）—— 必须先做

子进程每个执行轮次都要刷新心跳，否则会被误判 stale。涉及两个文件：

### 2.1 `src/multi_round_executor/executor.py`

**(A) 心跳文件路径解析** —— `_get_manager_status_file_path()`（约 L170-187）
返回 `<output_dir>/.agia_spawn_manager_status.json`。

**(B) 心跳写入器** —— `_create_or_update_manager_status_file()`（约 L189-260）
写入字段：
```json
{
  "agent_id": "manager",
  "status": "running",
  "task_description": "...",
  "start_time": "2026-07-02T16:14:36.000",
  "output_directory": "...",
  "model": "glm-4.7",
  "max_loops": 100,
  "current_loop": 3,
  "error": null,
  "last_loop_update": "2026-07-02T16:18:01.000"
}
```
**每轮必须刷新 `current_loop` 和 `last_loop_update`**（时间戳用 `datetime.now().isoformat()`）。

**(C) 主循环里调用心跳**（约 L993-999，`_execute_task_rounds` 内）
```python
# 每轮 task_round 执行后：
if is_manager:
    try:
        if self._create_or_update_manager_status_file(current_loop=task_round):
            print_debug(f"📝 Manager status file updated: current_loop = {task_round}")
    except Exception as e:
        print_debug(f"⚠️ Failed to update manager status file: {e}")
```

**(D) 启动时初始化、结束时写终态**（约 L634-638 初始化, L560-585 终态）
- 启动：`_create_or_update_manager_status_file(current_loop=0, task_desc=..., max_loops=...)`，状态 `running`。
- 结束：状态置 `completed`/`max_rounds_reached`，写 `completion_time`、`updated_at`。**这是看门狗判断"子进程是否真的结束"的依据**。

> **`last_loop_update` 是防卡死的生命线**：长 LLM 调用会冻结主循环，但只要上一轮写入了它，看门狗就能在 1800s 后判定 stale。若你要在长工具调用（如图谱/wikimemory 构建）期间也保持心跳，新增一个 `asset_update_in_progress.updated_at` 字段并在工具执行前后刷新——运行器侧的 `_spawn_status_last_progress_time()` 已经会把它纳入心跳判据（见 §3.3）。

### 2.2 `src/tools/multiagents.py`

多 agent 场景下，子 agent 也需更新自己的 `current_loop`（约 L1830-1917 `update_agent_current_loop`）。核心同样写 `current_loop` + `last_loop_update`。若你的目标版本是单 agent，可只保留 executor.py 那条。

---

## 3. 运行器侧改动（apps/scienceworld/run_all_tasks.py）—— 看门狗主体

### 3.1 配置常量（约 L51-113）

```python
MAX_TRANSIENT_PHASE_ATTEMPTS = max(1, int(os.environ.get("AGIA_TRANSIENT_PHASE_ATTEMPTS", "1") or 1))
PHASE_ZOMBIE_STALE_SECONDS = 1800   # 心跳超过 30 分钟无更新 → 判定卡死
RECOVERABLE_PHASE_RETURN_CODES = {129, 130, 137, 143, -9, -15}  # 信号类退出码可重试
TRANSIENT_MODEL_ERROR_MARKERS = (           # 模型/网关临时故障关键词
    "connection error", "readtimeout", "timed out", "rate limit",
    "bad gateway", "gateway timeout", "error code: 429/500/502/503/504", ...
)
RECOVERABLE_PHASE_INTERRUPTION_MARKERS = (   # 信号中断关键词
    "keyboardinterrupt", "killed", "terminated", "sigterm", "sigkill", ...
)
```

### 3.2 看门狗进程管理器 `_ExperimentLogger.run_process()`（约 L170-280）

**这是防卡死的核心**。与普通 `subprocess.run` 的关键差异：

```python
proc = subprocess.Popen(..., start_new_session=True)  # ★ 独立进程组, 便于干净 kill 整组
# 独立线程逐行读 stdout 到队列
while True:
    try:
        line = stdout_queue.get(timeout=1.0)   # ★ 每 1s 唤醒一次做心跳检查
    except queue.Empty:
        if proc.poll() is not None: break
        spawn_status = _load_spawn_manager_status(output_dir)   # ★ 读子进程心跳
        if _is_spawn_status_stale(spawn_status):                 # ★ 判定卡死
            proc.terminate()                                     # SIGTERM
            proc.wait(timeout=kill_grace_seconds)                # 20s 宽限
            except TimeoutExpired: proc.kill()                   # → SIGKILL
            terminated_for_stale = True
            break
        continue
# 被看门狗杀掉的, 强制 returncode=143 (而非子进程自报的 0)
if terminated_for_stale and returncode == 0: returncode = 143
```

**移植要点**：
- `start_new_session=True` 不可省——否则 SIGTERM 杀不掉子进程的孙子进程。
- 用「队列 + 1s 超时」轮询，**不要**用 `proc.communicate()`（会阻塞，无法插心跳检查）。
- 被看门狗杀掉的进程，把 returncode 从 0 改写为 143，下游才会归类为「需要重试」而非「成功」。

### 3.3 卡死与故障判定函数（约 L691-968）

| 函数 | 作用 |
|---|---|
| `_load_spawn_manager_status(out_dir)` | 读 `.agia_spawn_manager_status.json` |
| `_spawn_status_last_progress_time(s)` | 取 `last_loop_update`/`updated_at`/`start_time`/`asset_update_in_progress.updated_at` 中**最新**的时间戳。★ 取最大值而非单个字段——避免长 LLM 调用冻结 `last_loop_update` 时误判 |
| `_is_spawn_status_stale(s)` | status∈{running,pending} 且无 completion_time 且 last_progress_time 距今 ≥ stale_seconds（默认 1800s） |
| `_mark_spawn_status_terminal(...)` | 看门狗杀进程后，回写终态 `terminated_stale`/`stale_killed=true`，供下游识别 |
| `_detect_transient_model_error(...)` | 扫描日志尾 + score_summary，命中 `TRANSIENT_MODEL_ERROR_MARKERS` → 归类为「可重试的临时故障」 |
| `_detect_recoverable_phase_interruption(...)` | returncode∈信号集 或 命中中断关键词 或 spawn_status 卡 running → 「可重试的中断」 |

### 3.4 分类重试循环 `_run_phase()`（约 L1454-1569）

```python
for attempt in range(1, MAX_TRANSIENT_PHASE_ATTEMPTS + 1):
    returncode = logger.run_process(...)          # 跑子进程(内含看门狗)
    score_summary = _load_score_summary(out_dir)
    spawn_status = _load_spawn_manager_status(out_dir)

    transient_reason = _detect_transient_model_error(...)
    recoverable_reason = _detect_recoverable_phase_interruption(...)

    # 优先级: 可恢复中断 > 临时模型错误
    retry_kind = "recoverable_interruption" if recoverable_reason else (
                 "transient_model_error" if transient_reason else "")
    if not retry_reason or attempt >= MAX_TRANSIENT_PHASE_ATTEMPTS:
        return phase_result                        # 不重试: 正常结束 / 达上限

    # 可恢复中断: 归档旧工作区(避免脏状态), 短延迟重试
    if retry_kind == "recoverable_interruption":
        _archive_phase_workspace_for_retry(out_dir, attempt)   # ★ mv 到 __stale_retry{N}_{ts}
        delay = min(12, _transient_retry_delay_seconds(...))
    else:  # 临时模型错误: 退避重试
        delay = _transient_retry_delay_seconds(...)
    time.sleep(delay)
```

**移植要点**：
- `_archive_phase_workspace_for_retry` 把卡死的工作区**改名归档**（`xxx__stale_retry1_20260702_...`）而非删除——保留现场用于排查，且新尝试用干净目录。★ 这是避免「脏状态导致再次卡死」的关键。
- `MAX_TRANSIENT_PHASE_ATTEMPTS` 默认 1（不重试），生产用环境变量 `AGIA_TRANSIENT_PHASE_ATTEMPTS=N` 开启。

---

## 4. 移植检查清单（给另一版本）

按依赖顺序，子进程侧优先：

### 子进程侧（src/）
- [ ] `executor.py`：实现 `_get_manager_status_file_path()` + `_create_or_update_manager_status_file(current_loop, ...)`
- [ ] `executor.py`：主循环每轮末尾调用心跳更新（`is_manager` 分支）
- [ ] `executor.py`：启动初始化（status=running, current_loop=0）+ 结束写终态（completion_time）
- [ ] `multiagents.py`：多 agent 场景的 `update_agent_current_loop()`（单 agent 可跳过）
- [ ] （可选增强）长工具调用前后刷新 `asset_update_in_progress.updated_at` 心跳

### 运行器侧（run_all_tasks.py 或等价批量脚本）
- [ ] 配置常量：`PHASE_ZOMBIE_STALE_SECONDS`、`RECOVERABLE_PHASE_RETURN_CODES`、两组 MARKERS
- [ ] `_load_spawn_manager_status` / `_spawn_status_last_progress_time` / `_is_spawn_status_stale` / `_mark_spawn_status_terminal`
- [ ] `_detect_transient_model_error` / `_detect_recoverable_phase_interruption`
- [ ] `_archive_phase_workspace_for_retry`
- [ ] 看门狗 `run_process`：`start_new_session=True` + 队列轮询 + 1s 心跳检查 + SIGTERM→SIGKILL + returncode=143 改写
- [ ] 重试循环 `_run_phase`：分类 + 归档 + 退避

---

## 5. 验证方法

移植后用以下手段验证防卡死生效：

1. **心跳写入**：跑一个 phase，确认 `<out_dir>/.agia_spawn_manager_status.json` 存在且 `last_loop_update` 随轮次推进。
2. **看门狗杀进程**：临时把 `AGIA_PHASE_ZOMBIE_STALE_SECONDS=30`（30s）+ 子进程里人为 sleep 不更新心跳 → 30s 后应看到日志 `detected stalled child process, sending SIGTERM`，工作区被 `__stale_retry1_` 归档。
3. **临时故障重试**：`AGIA_TRANSIENT_PHASE_ATTEMPTS=2`，模拟网关 502 → 应看到 `detected transient model/provider failure ... retrying`。
4. **进程组隔离**：杀掉的进程不应残留孤儿（`ps -ef | grep agia` 确认无遗留）。

> 仍存在的缺口（本次故障暴露）：模型返回 **200 OK 但空内容** 时，主调用路径（`src/api_callers/openai_chat_based_streaming.py:199`）不检测空响应、不抛错，看门狗的心跳仍在更新（因为轮次在推进），所以**不会**被 stale 检测捕获——表现为 100 轮空转得 0 分。若你的目标版本也走该 API 路径，建议额外在 `return content, standardized_tool_calls` 前加 `if not content.strip(): raise ValueError("Empty LLM response")` 以触发既有重试逻辑。这不在原防卡死改动范围内，但属于同类根因的补强。
