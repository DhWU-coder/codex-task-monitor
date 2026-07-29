# 陈旧运行状态对账实施计划

> **For implementation:** REQUIRED: Use superpowers:executing-plans to implement this plan in the current session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 App Server 线程详情中的权威 Turn 终态，纠正本地会话缺少结束事件造成的陈旧运行状态。

**Architecture:** `RuntimeService.refresh_once()` 在处理 App Server 列表快照时，通过独立判定函数决定是否读取线程详情。列表本身活跃时维持原行为；列表为 unknown 且聚合器仍认为同一线程活跃时补读详情，读取失败则保留原状态。

**Tech Stack:** Python、asyncio、pytest、FastAPI 现有运行时。

**Design:** `docs/superpowers/specs/2026-07-29-stale-running-reconciliation-design.md`

---

## Chunk 1：陈旧活动状态对账

### Task 1：以测试复现真实故障链

**Files:**
- Modify: `tests/integration/test_runtime.py`
- Test: `tests/integration/test_runtime.py`

- [x] **Step 1: 增加可配置的 notLoaded 假 App Server**

构造一个测试客户端：`thread/list` 返回近期 `notLoaded` 线程和空 Turn 列表；`thread/read` 可返回最新 Turn 为 `interrupted`，也可模拟读取失败。扩展 `_runtime()` 允许注入该客户端。

- [x] **Step 2: 编写陈旧 running 被 interrupted 纠正的失败测试**

先通过会话观察事件把同一线程标记为 `running`，再执行 `refresh_once()`；断言调用了 `thread/read`、任务变为 `interrupted` 且未监控任务不发送通知。

- [x] **Step 3: 编写边界失败测试**

验证聚合器中没有活动状态的普通 `notLoaded` 线程不读取详情；验证详情读取失败时已有 `running` 保持不变。

- [x] **Step 4: 运行目标测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/integration/test_runtime.py -q`

Expected: FAIL，核心用例和详情读取失败用例都没有调用 `thread/read`；普通历史线程用例通过。

### Task 2：实现详情对账条件

**Files:**
- Modify: `codex_task_monitor/runtime.py`
- Test: `tests/integration/test_runtime.py`

- [x] **Step 1: 提取活动状态集合和纯判定函数**

新增模块级 `ACTIVE_STATUSES`，并实现 `_needs_thread_details(listed, current)`：列表状态活跃时返回真；列表为 `unknown` 且现有状态活跃时返回真；其他情况返回假。

- [x] **Step 2: 接入 refresh_once**

每个列表快照映射后先读取聚合器现有快照，并用 `_needs_thread_details()` 决定是否调用现有 `_read_active_thread()`；不修改详情读取失败的回退行为。

- [x] **Step 3: 运行目标测试和静态检查**

Run: `.venv/bin/python -m pytest tests/integration/test_runtime.py tests/unit/test_aggregator.py tests/unit/test_app_server_mapper.py -q`

Expected: PASS，对账、聚合器和映射器测试全部通过。

Run: `.venv/bin/python -m ruff check codex_task_monitor/runtime.py tests/integration/test_runtime.py && .venv/bin/python -m mypy codex_task_monitor`

Expected: PASS，Ruff 和 mypy 通过。

### Task 3：完整验证与变更检查

**Files:**
- Modify: `docs/superpowers/plans/2026-07-29-stale-running-reconciliation.md`

- [x] **Step 1: 运行完整 Python 验证**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check . && .venv/bin/python -m mypy codex_task_monitor`

Expected: PASS，全部 Python 测试和静态检查通过。

- [x] **Step 2: 运行前端回归验证**

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run typecheck && npm --prefix frontend run build && npm --prefix frontend audit --omit=dev`

Expected: PASS，前端测试、类型检查和构建通过，生产依赖无已知漏洞。

- [x] **Step 3: 检查最终范围和运行中服务**

Run: `git diff --check && git status --short --branch`

Expected: 保留之前已确认的 run/start 本地变更，并新增本次运行时、回归测试、设计和计划文档；不执行服务重启、Git 提交或推送。
