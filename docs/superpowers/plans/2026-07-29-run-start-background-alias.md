# Run 与 Start 后台别名实施计划

> **For implementation:** REQUIRED: Use superpowers:executing-plans to implement this plan in the current session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `codex-task-monitor run` 与 `start` 完全等价地幂等启动后台服务并打印 UI 地址。

**Architecture:** 在现有 Typer CLI 模块中提取共享后台启动命令处理函数，两个公开命令只负责注册名称并调用它；内部 `_serve` 和现有后台生命周期函数保持不变。通过 CLI Runner 参数化测试证明两条命令的成功、已运行和失败输出一致。

**Tech Stack:** Python、Typer、pytest。

**Design:** `docs/superpowers/specs/2026-07-29-run-start-background-alias-design.md`

---

## Chunk 1：CLI 后台别名与文档

### Task 1：以测试定义等价后台行为

**Files:**
- Modify: `tests/unit/test_cli.py`
- Test: `tests/unit/test_cli.py`

- [x] **Step 1: 编写 run/start 共用后台启动的失败测试**

使用 `pytest.mark.parametrize` 对 `run` 和 `start` 执行相同断言：两者调用 `_start_background`、不调用 `_run_foreground`、输出后台启动返回的 UI 地址。

- [x] **Step 2: 编写已运行和启动失败的失败测试**

参数化验证 `StartResult.already_running=True` 时两条命令都提示“监控器已在运行”；验证 `_start_background` 抛出 `RuntimeError` 时两条命令都返回退出码 `1` 并输出“启动失败”。

- [x] **Step 3: 运行目标测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/unit/test_cli.py -q`

Expected: FAIL，其中 `run` 用例因仍调用 `_run_foreground` 而失败，`start` 用例保持通过。

### Task 2：实现共享后台启动入口

**Files:**
- Modify: `codex_task_monitor/cli.py`
- Test: `tests/unit/test_cli.py`

- [x] **Step 1: 提取共享命令处理函数**

新增 `_launch_background_command()`，集中加载配置、调用 `_start_background`、处理 `RuntimeError`、输出已运行提示与 UI 地址。

- [x] **Step 2: 让 run 和 start 调用共享函数**

修改两个公开命令的中文说明并调用 `_launch_background_command()`；保留 `_run_foreground()`，把 `_serve` 说明更新为供 `run` 和 `start` 后台进程使用。

- [x] **Step 3: 运行目标测试和静态检查**

Run: `.venv/bin/python -m pytest tests/unit/test_cli.py -q && .venv/bin/python -m ruff check codex_task_monitor/cli.py tests/unit/test_cli.py && .venv/bin/python -m mypy codex_task_monitor`

Expected: PASS，CLI 测试、Ruff 和 mypy 均通过。

### Task 3：更新用户文档并完整验证

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-29-run-start-background-alias.md`

- [x] **Step 1: 更新 README CLI 说明**

把 `run` 和 `start` 都描述为后台、幂等且互为别名；保留 `stop` 和 `restart` 原说明。

- [x] **Step 2: 运行完整后端验证**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check . && .venv/bin/python -m mypy codex_task_monitor`

Expected: PASS，全部 Python 测试和静态检查通过。

- [x] **Step 3: 运行完整前端回归验证**

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run typecheck && npm --prefix frontend run build && npm --prefix frontend audit --omit=dev`

Expected: PASS，前端测试、类型检查和构建通过，生产依赖无已知漏洞。

- [x] **Step 4: 检查最终变更与运行中服务状态**

Run: `git diff --check && git status --short --branch`

Expected: 只有本次 CLI、测试、README、设计和计划文档变更；不执行 `stop`、`restart`、提交或推送。
