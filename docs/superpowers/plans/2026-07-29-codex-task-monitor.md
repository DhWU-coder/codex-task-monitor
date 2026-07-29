# Codex 任务监控器实施计划

> **For implementation:** REQUIRED: Use superpowers:executing-plans to implement this plan in the current session. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在当前目录实现一个可通过 CLI 管理的本地 Web 应用，实时展示本机 Codex 任务，并按用户选择向飞书私聊发送幂等状态通知。

**Architecture:** Python/FastAPI 后端通过官方 Codex App Server 与只读本地会话观察器聚合任务状态，使用 SQLite 保存监控和通知记录，通过 REST/SSE 服务 Vue 3 卡片 UI。CLI 统一管理前台和后台生命周期，飞书客户端通过自建应用凭据发送私聊消息。

**Tech Stack:** Python 3.14、FastAPI、Uvicorn、Pydantic、PyYAML、HTTPX、SQLite、Typer、pytest、Vue 3、TypeScript、Vite、Vitest、Playwright。

**Design:** `docs/superpowers/specs/2026-07-29-codex-task-monitor-design.md`

---

## 文件结构

计划创建以下文件，每个文件保持单一职责：

```text
pyproject.toml                                  # Python 包、依赖、CLI 入口和检查工具
config.yaml                                    # 默认运行配置，端口 6664
.gitignore                                     # 排除密钥配置、运行数据和构建缓存
README.md                                      # 安装、CLI、飞书配置和安全边界
codex_task_monitor/
  __init__.py
  paths.py                                     # 配置、数据、PID 和日志路径解析
  models.py                                    # 跨模块领域模型
  runtime.py                                   # 后台服务生命周期编排
  cli.py                                       # start/run/stop/restart
  config/
    __init__.py
    models.py                                  # Pydantic 配置模型
    service.py                                 # YAML 原子读写、遮罩和热更新
  storage/
    __init__.py
    database.py                                # SQLite schema、事务和权限
    repository.py                              # 监控与通知持久化接口
  codex_adapter/
    __init__.py
    client.py                                  # App Server JSON-RPC stdio 客户端
    mapper.py                                  # App Server 数据到领域模型的映射
  session_observer/
    __init__.py
    parser.py                                  # 本地会话 JSONL 记录解析
    observer.py                                # 只读文件发现和增量读取
  monitoring/
    __init__.py
    aggregator.py                              # 多来源状态合并
    service.py                                 # 监控模式、恢复和通知决策
    project_info.py                            # 项目名和 Git 分支只读提取
  notifications/
    __init__.py
    formatter.py                               # 飞书文本消息格式化
    feishu.py                                  # Token、发送和重试
  web/
    __init__.py
    app.py                                     # FastAPI 应用工厂和 lifespan
    api.py                                     # REST 路由
    events.py                                  # SSE 广播
    security.py                                # Host、同源和 CSRF 校验
    schemas.py                                 # Web 请求和响应模型
    static/                                    # 前端构建产物
schemas/codex-app-server/                      # 本机 Codex 版本生成的 JSON Schema
frontend/
  package.json
  package-lock.json
  index.html
  vite.config.ts
  tsconfig.json
  tsconfig.app.json
  src/
    main.ts
    App.vue
    api.ts
    types.ts
    styles.css
    components/
      StatusBar.vue
      FilterTabs.vue
      TaskCard.vue
      TaskDetails.vue
      SettingsPanel.vue
  tests/
    api.test.ts
    App.test.ts
    SettingsPanel.test.ts
tests/
  conftest.py
  unit/
    test_config_service.py
    test_database.py
    test_project_info.py
    test_monitoring_service.py
    test_formatter.py
    test_feishu.py
    test_app_server_mapper.py
    test_session_parser.py
    test_aggregator.py
    test_cli.py
  integration/
    fake_app_server.py
    test_app_server_client.py
    test_session_observer.py
    test_web_api.py
    test_runtime.py
  fixtures/
    sessions/                                  # 脱敏 Codex 会话样例
```

## Chunk 1：基础设施、领域模型与通知

### Task 1：建立 Python 项目与默认配置

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `config.yaml`
- Create: `codex_task_monitor/__init__.py`
- Create: `codex_task_monitor/paths.py`
- Create: `codex_task_monitor/config/__init__.py`
- Create: `codex_task_monitor/config/models.py`
- Create: `codex_task_monitor/config/service.py`
- Create: `tests/conftest.py`
- Test: `tests/unit/test_config_service.py`

- [x] **Step 1: 创建包元数据并安装开发依赖**

在 `pyproject.toml` 中声明 FastAPI、Uvicorn、Pydantic、PyYAML、HTTPX、Typer，以及 pytest、pytest-asyncio、respx、ruff、mypy、types-PyYAML；注册：

```toml
[project.scripts]
codex-task-monitor = "codex_task_monitor.cli:app"
```

同时创建最小 `codex_task_monitor/__init__.py`，确保可编辑安装能够发现包。

Run: `.venv/bin/python -m pip install -e '.[dev]'`

Expected: 依赖安装成功，`.venv/bin/python -m pytest --version` 正常输出版本。

- [x] **Step 2: 编写配置解析和路径稳定性的失败测试**

```python
def test_default_port_is_6664(tmp_path):
    service = ConfigService(tmp_path / "config.yaml")
    service.create_default()
    assert service.load().server.port == 6664

def test_masked_config_never_exposes_app_secret(config_service):
    masked = config_service.to_public_dict()
    assert masked["feishu"]["app_secret"] == ""
    assert masked["feishu"]["app_secret_configured"] is True
```

- [x] **Step 3: 运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/unit/test_config_service.py -q`

Expected: FAIL，原因是配置模块尚不存在。

- [x] **Step 4: 实现配置模型、路径解析和原子保存**

实现：

```python
class ServerConfig(BaseModel):
    host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    port: int = Field(default=6664, ge=1024, le=65535)

class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    codex: CodexConfig = CodexConfig()
    feishu: FeishuConfig = FeishuConfig()
    notifications: NotificationConfig = NotificationConfig()
```

配置保存使用同目录临时文件、`fsync`、`os.replace` 和 `chmod(0o600)`；`app_secret` 留空时保留旧值，只有 `clear_app_secret=true` 时清除。

- [x] **Step 5: 运行配置测试和静态检查**

Run: `.venv/bin/python -m pytest tests/unit/test_config_service.py -q && .venv/bin/python -m ruff check codex_task_monitor/config codex_task_monitor/paths.py tests/unit/test_config_service.py`

Expected: 全部 PASS，无 Ruff 错误。

所有新增代码注释和 docstring 使用中文。

### Task 2：建立领域模型和 SQLite 仓储

**Files:**
- Create: `codex_task_monitor/models.py`
- Create: `codex_task_monitor/storage/__init__.py`
- Create: `codex_task_monitor/storage/database.py`
- Create: `codex_task_monitor/storage/repository.py`
- Test: `tests/unit/test_database.py`

- [x] **Step 1: 编写 schema、监控恢复和幂等写入失败测试**

```python
def test_notification_key_is_unique(repository):
    assert repository.reserve_notification("thread:turn:completed") is True
    assert repository.reserve_notification("thread:turn:completed") is False

def test_recovery_deactivates_non_running_watch(repository):
    repository.save_watch(thread_id="t1", mode="persistent", active=True)
    repository.restore_watches({"t1": TaskStatus.COMPLETED})
    assert repository.get_watch("t1").active is False
```

- [x] **Step 2: 运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/unit/test_database.py -q`

Expected: FAIL，原因是领域模型和仓储尚不存在。

- [x] **Step 3: 实现聚焦的领域模型**

至少定义：

```python
class TaskStatus(StrEnum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"
    SOURCE_ERROR = "source_error"
```

以及 `TaskSnapshot`、`TurnSnapshot`、`WatchRecord`、`NotificationEvent`、`SourceHealth`。

- [x] **Step 4: 实现 SQLite 初始化和仓储事务**

创建 `watches`、`notifications`、`task_snapshots` 表。使用唯一 `dedupe_key`；数据库目录权限 `0700`、数据库权限 `0600`。所有通知预留、成功和失败更新必须在明确事务中完成。

- [x] **Step 5: 运行仓储测试**

Run: `.venv/bin/python -m pytest tests/unit/test_database.py -q`

Expected: PASS。

### Task 3：实现项目和 Git 信息提取

**Files:**
- Create: `codex_task_monitor/monitoring/__init__.py`
- Create: `codex_task_monitor/monitoring/project_info.py`
- Test: `tests/unit/test_project_info.py`

- [x] **Step 1: 编写 Git 仓库、非 Git 目录和超时测试**

```python
def test_uses_thread_git_info_before_running_git():
    info = resolve_project_info("/work/repo", {"branch": "feature/x"})
    assert info.branch == "feature/x"

def test_non_git_directory_uses_directory_name(tmp_path):
    assert resolve_project_info(str(tmp_path), None).project_name == tmp_path.name
```

- [x] **Step 2: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/unit/test_project_info.py -q`

Expected: FAIL，模块尚不存在。

- [x] **Step 3: 实现只读 Git 查询**

使用 `asyncio.create_subprocess_exec("git", "-C", cwd, ...)`，禁止 Shell 拼接，超时 1 秒；优先线程 `gitInfo`，Git 查询失败时返回无分支结果而非抛出。

- [x] **Step 4: 运行测试**

Run: `.venv/bin/python -m pytest tests/unit/test_project_info.py -q`

Expected: PASS。

### Task 4：实现监控状态机和通知决策

**Files:**
- Create: `codex_task_monitor/monitoring/service.py`
- Test: `tests/unit/test_monitoring_service.py`

- [x] **Step 1: 编写当前轮、持续模式、等待事件和重启恢复失败测试**

```python
async def test_current_turn_stops_after_terminal_event(service):
    await service.start_watch(running_task, mode=WatchMode.CURRENT_TURN)
    events = await service.apply(completed_task)
    assert [event.status for event in events] == [TaskStatus.COMPLETED]
    assert service.watch_for(running_task.thread_id).active is False

async def test_persistent_watch_accepts_next_turn(service):
    await service.start_watch(turn_one, mode=WatchMode.PERSISTENT)
    await service.apply(turn_one_completed)
    events = await service.apply(turn_two_waiting_input)
    assert events[0].status == TaskStatus.WAITING_INPUT
```

- [x] **Step 2: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/unit/test_monitoring_service.py -q`

Expected: FAIL。

- [x] **Step 3: 实现基线、转换和幂等规则**

实现：

- 启用时记录当前 Turn 和状态，不为基线发送通知；
- 等待事件按请求或 Item ID 去重；
- 终态按线程、Turn 和状态去重；
- 当前轮终态后停用；
- 持续模式接收同线程新 Turn；
- 恢复时只保留仍在运行或等待的记录；
- 数据源断开或未知状态不产生终态事件。

- [x] **Step 4: 运行状态机测试**

Run: `.venv/bin/python -m pytest tests/unit/test_monitoring_service.py -q`

Expected: PASS。

### Task 5：实现飞书消息格式和客户端

**Files:**
- Create: `codex_task_monitor/notifications/__init__.py`
- Create: `codex_task_monitor/notifications/formatter.py`
- Create: `codex_task_monitor/notifications/feishu.py`
- Test: `tests/unit/test_formatter.py`
- Test: `tests/unit/test_feishu.py`

- [x] **Step 1: 编写消息字段、摘要截断和敏感信息失败测试**

```python
def test_terminal_message_contains_project_and_branch():
    text = format_notification(completed_event, max_length=500)
    assert "项目：codex-task-monitor" in text
    assert "分支：feature/monitor" in text
    assert "状态：已完成" in text

def test_formatter_redacts_access_tokens():
    assert "t-secret" not in format_notification(event_with_secret)
```

- [x] **Step 2: 编写 token 缓存、鉴权刷新、限流和权限错误失败测试**

使用 `respx` 模拟：

- 获取 `tenant_access_token`；
- 成功发送 `msg_type=text`；
- 鉴权失败后只刷新一次；
- 429 和 5xx 最多重试三次；
- 230013 等配置错误不循环重试。

- [x] **Step 3: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/unit/test_formatter.py tests/unit/test_feishu.py -q`

Expected: FAIL。

- [x] **Step 4: 实现格式化器和飞书客户端**

调用官方端点：

```text
POST /open-apis/auth/v3/tenant_access_token/internal
POST /open-apis/im/v1/messages?receive_id_type=open_id
```

令牌只保存在内存；消息内容使用 `json.dumps({"text": text}, ensure_ascii=False)`；日志只记录错误码和飞书 `message_id`，不记录凭据或接收人 ID。

- [x] **Step 5: 运行通知测试**

Run: `.venv/bin/python -m pytest tests/unit/test_formatter.py tests/unit/test_feishu.py -q`

Expected: PASS。

- [x] **Step 6: 验证 Chunk 1**

Run: `.venv/bin/python -m pytest tests/unit/test_config_service.py tests/unit/test_database.py tests/unit/test_project_info.py tests/unit/test_monitoring_service.py tests/unit/test_formatter.py tests/unit/test_feishu.py -q`

Expected: 全部 PASS。检查所有代码注释均为中文，不执行 Git 暂存、提交或推送。

## Chunk 2：Codex 数据采集、聚合、Web API 与 CLI

### Task 6：核验本机 Codex Schema 和脱敏会话格式

**Files:**
- Create: `schemas/codex-app-server/`
- Create: `tests/fixtures/sessions/`

- [x] **Step 1: 生成与本机 CLI 匹配的 JSON Schema**

Run: `codex app-server generate-json-schema --out schemas/codex-app-server`

Expected: 命令成功，并生成 `thread/list`、`thread/read`、Turn 和通知相关 schema 文件。

- [x] **Step 2: 只读检查本机会话目录结构和记录类型**

Run: `find "${CODEX_HOME:-$HOME/.codex}/sessions" -type f -name '*.jsonl' | tail -n 5`

Expected: 找到零个或多个会话 JSONL；命令不修改文件。

- [x] **Step 3: 创建最小脱敏夹具**

从本地记录结构手工创建不含真实对话、路径、令牌和用户标识的测试夹具，覆盖线程元数据、Turn 开始、等待事件、完成、失败和中断。禁止复制真实聊天内容到测试文件。

- [x] **Step 4: 核验夹具不含敏感信息**

Run: `rg -n '/Users/|app_secret|tenant_access_token|Authorization|Bearer ' tests/fixtures/sessions || true`

Expected: 无输出。

### Task 7：实现 App Server JSON-RPC 客户端和映射

**Files:**
- Create: `codex_task_monitor/codex_adapter/__init__.py`
- Create: `codex_task_monitor/codex_adapter/client.py`
- Create: `codex_task_monitor/codex_adapter/mapper.py`
- Create: `tests/integration/fake_app_server.py`
- Create: `tests/integration/test_app_server_client.py`
- Create: `tests/unit/test_app_server_mapper.py`

- [x] **Step 1: 编写握手、并发请求、事件和退出失败测试**

```python
async def test_client_initializes_before_listing_threads(fake_server):
    client = AppServerClient(fake_server.command)
    await client.start()
    result = await client.request("thread/list", {"useStateDbOnly": True})
    assert result["data"][0]["id"] == "thread-1"
    assert fake_server.received_methods[:3] == [
        "initialize", "initialized", "thread/list"
    ]
```

同时覆盖无效 JSON、stderr 日志、请求超时、子进程退出、取消未完成请求和指数退避。

- [x] **Step 2: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/integration/test_app_server_client.py tests/unit/test_app_server_mapper.py -q`

Expected: FAIL。

- [x] **Step 3: 实现异步 JSONL 客户端**

要求：

- 使用 `asyncio.create_subprocess_exec`；
- stdout 按行解析，stderr 单独读取；
- 请求 ID 与 Future 映射；
- 初始化后才允许业务请求；
- 退出时取消所有 pending 请求；
- 通知通过异步回调或队列发布；
- 不把原始消息或凭据写入普通日志。

- [x] **Step 4: 实现 App Server 领域映射**

映射 `thread.status.type`、`activeFlags`、最新 Turn、错误、标题、cwd 和 `gitInfo`。审批和输入请求保留请求 ID 与安全摘要。未知枚举降级为 `unknown`。

- [x] **Step 5: 运行客户端和映射测试**

Run: `.venv/bin/python -m pytest tests/integration/test_app_server_client.py tests/unit/test_app_server_mapper.py -q`

Expected: PASS。

### Task 8：实现本地会话解析器和只读观察器

**Files:**
- Create: `codex_task_monitor/session_observer/__init__.py`
- Create: `codex_task_monitor/session_observer/parser.py`
- Create: `codex_task_monitor/session_observer/observer.py`
- Test: `tests/unit/test_session_parser.py`
- Test: `tests/integration/test_session_observer.py`

- [x] **Step 1: 编写脱敏记录映射失败测试**

覆盖线程元数据、Turn 开始、等待、完成、失败、中断、Agent 最新摘要和未知记录。

- [x] **Step 2: 编写增量读取失败测试**

覆盖：

- 启动时读取近期会话的元数据头和有界尾部，能够识别已经运行中的任务，但只建立通知基线；
- 新追加完整行；
- 半行等待下次读取；
- inode 替换和截断；
- 重复行不重复发事件；
- 观察器从不以写模式打开文件。

- [x] **Step 3: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/unit/test_session_parser.py tests/integration/test_session_observer.py -q`

Expected: FAIL。

- [x] **Step 4: 实现版本隔离的解析器**

解析函数只接受字典并返回零个或多个标准化来源事件；不识别的记录返回空列表，关键字段损坏返回结构化解析错误。摘要先清除潜在凭据，再按配置截断。

- [x] **Step 5: 实现轮询式只读观察器**

首版使用异步轮询而不是平台专用 FSEvents，按路径、inode、size 和 offset 保存游标。启动时读取近期会话的元数据头，并回放不超过 2 MiB 的文件尾部以建立当前状态基线；基线事件不得进入通知发送流程。之后只增量观察近期活动文件；每次读取限制字节数，避免大历史文件阻塞事件循环。

- [x] **Step 6: 运行解析和观察测试**

Run: `.venv/bin/python -m pytest tests/unit/test_session_parser.py tests/integration/test_session_observer.py -q`

Expected: PASS。

### Task 9：实现多来源聚合和运行时编排

**Files:**
- Create: `codex_task_monitor/monitoring/aggregator.py`
- Create: `codex_task_monitor/runtime.py`
- Test: `tests/unit/test_aggregator.py`
- Test: `tests/integration/test_runtime.py`

- [x] **Step 1: 编写来源优先级、冲突和断线失败测试**

```python
def test_disconnect_never_becomes_completed(aggregator):
    aggregator.apply(app_server_running)
    snapshot = aggregator.apply(app_server_disconnected)
    assert snapshot.status in {TaskStatus.RUNNING, TaskStatus.UNKNOWN}
    assert snapshot.status is not TaskStatus.COMPLETED
```

同时验证本地终态需确认、App Server 终态优先、最近摘要合并和来源健康状态。

- [x] **Step 2: 编写运行时刷新和通知队列失败测试**

使用 fake App Server、临时会话目录、临时 SQLite 和模拟飞书客户端，验证两秒刷新、三十秒对账、SSE 发布和幂等通知。

- [x] **Step 3: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/unit/test_aggregator.py tests/integration/test_runtime.py -q`

Expected: FAIL。

- [x] **Step 4: 实现聚合器**

按设计中的来源优先级和终态确认规则维护不可变 `TaskSnapshot`；仅在内容变化时发布新快照。

- [x] **Step 5: 实现运行时服务**

运行时负责：

- App Server 连接和重连；
- `thread/list` 使用 `useStateDbOnly: true` 和 `["cli", "vscode", "exec", "appServer", "unknown"]`；
- 活动或监控任务的 `thread/read`；
- 会话观察循环；
- 周期对账；
- 监控决策；
- 飞书发送队列；
- 优雅关闭。

- [x] **Step 6: 运行聚合和运行时测试**

Run: `.venv/bin/python -m pytest tests/unit/test_aggregator.py tests/integration/test_runtime.py -q`

Expected: PASS。

### Task 10：实现安全的 REST API 和 SSE

**Files:**
- Create: `codex_task_monitor/web/__init__.py`
- Create: `codex_task_monitor/web/app.py`
- Create: `codex_task_monitor/web/api.py`
- Create: `codex_task_monitor/web/events.py`
- Create: `codex_task_monitor/web/security.py`
- Create: `codex_task_monitor/web/schemas.py`
- Test: `tests/integration/test_web_api.py`

- [x] **Step 1: 编写任务、监控、配置、健康和 SSE 失败测试**

至少覆盖：

- `GET /api/tasks`；
- `GET /api/tasks/{thread_id}`；
- `POST /api/tasks/{thread_id}/watch`；
- `DELETE /api/tasks/{thread_id}/watch`；
- `GET/PUT /api/config`；
- `POST /api/notifications/test`；
- `POST /api/notifications/{id}/retry`；
- `GET /api/events`；
- `GET /healthz`。

- [x] **Step 2: 编写 Host、CSRF、同源和密钥遮罩失败测试**

```python
def test_config_response_never_contains_secret(client):
    response = client.get("/api/config")
    assert response.json()["feishu"]["app_secret"] == ""

def test_mutation_requires_csrf(client):
    response = client.post("/api/tasks/t1/watch", json={"mode": "persistent"})
    assert response.status_code == 403
```

- [x] **Step 3: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/integration/test_web_api.py -q`

Expected: FAIL。

- [x] **Step 4: 实现应用工厂和安全中间件**

使用依赖注入传入运行时；限制 Host；不启用 CORS；首次加载页面时设置 SameSite=Strict 的 CSRF Cookie，并要求修改请求同时携带请求头；校验同源 Origin/Referer。

- [x] **Step 5: 实现 REST 和 SSE**

所有响应使用安全投影。SSE 每 15 秒发送心跳；断线时移除订阅队列；慢客户端使用有界队列并要求重新获取快照。

- [x] **Step 6: 运行 Web API 测试**

Run: `.venv/bin/python -m pytest tests/integration/test_web_api.py -q`

Expected: PASS。

### Task 11：实现 CLI 生命周期

**Files:**
- Create: `codex_task_monitor/cli.py`
- Modify: `codex_task_monitor/paths.py`
- Test: `tests/unit/test_cli.py`

- [x] **Step 1: 编写 run/start/stop/restart 失败测试**

使用 Typer `CliRunner` 和临时配置验证：

- 默认 URL 为 `http://127.0.0.1:6664`；
- 配置端口改变后打印新 URL；
- `start` 等待健康检查；
- 重复 `start` 不产生第二进程；
- `stop` 处理正常与陈旧 PID；
- `restart` 调用先停后启；
- 从不同 cwd 调用仍读取同一配置。

- [x] **Step 2: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/unit/test_cli.py -q`

Expected: FAIL。

- [x] **Step 3: 实现 `run`**

加载配置，创建 FastAPI 应用，通过 Uvicorn 前台运行；启动完成时打印 UI 地址；SIGINT/SIGTERM 进入统一优雅关闭流程。

- [x] **Step 4: 实现 `start`**

使用 `start_new_session=True` 启动内部服务命令；写 PID 和运行元数据；日志重定向到 `data/codex-task-monitor.log`；轮询 `/healthz`，成功后打印 URL。

- [x] **Step 5: 实现 `stop` 和 `restart`**

停止前验证 PID 进程命令属于 `codex_task_monitor`；先 SIGTERM，超时后只对已验证目标发送 SIGKILL；清理运行文件。`restart` 串联停止和启动。

- [x] **Step 6: 运行 CLI 测试**

Run: `.venv/bin/python -m pytest tests/unit/test_cli.py -q`

Expected: PASS。

- [x] **Step 7: 验证 Chunk 2**

Run: `.venv/bin/python -m pytest tests/unit tests/integration -q`

Expected: 全部 PASS。确认未操作真实 Codex 任务，未发送真实飞书消息，未执行 Git 写操作。

## Chunk 3：Vue UI、打包、文档与端到端验证

### Task 12：建立 Vue 前端和 API 客户端

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/styles.css`
- Create: `frontend/tests/api.test.ts`

- [x] **Step 1: 创建最小 Vue/Vite/Vitest 配置**

依赖 Vue 3；开发依赖 TypeScript、Vite、Vitest、Vue Test Utils、jsdom。构建输出指向 `codex_task_monitor/web/static`。

Run: `cd frontend && npm install`

Expected: 安装成功并生成 `package-lock.json`。

- [x] **Step 2: 编写 API 客户端失败测试**

覆盖安全投影反序列化、CSRF Cookie、修改请求头、API 错误和 SSE URL。

- [x] **Step 3: 运行失败测试**

Run: `cd frontend && npm test -- --run tests/api.test.ts`

Expected: FAIL，原因是 API 客户端尚未实现。

- [x] **Step 4: 编写类型和 API 客户端**

定义与后端安全投影一致的 `TaskSnapshot`、`SourceHealth`、`PublicConfig` 和 `WatchMode`；统一读取 CSRF Cookie，并只在修改请求中发送请求头。

- [x] **Step 5: 运行测试、类型检查和空构建**

Run: `cd frontend && npm test -- --run tests/api.test.ts && npm run typecheck && npm run build`

Expected: 安装成功、类型检查通过、生成静态构建目录。

### Task 13：实现状态栏、筛选和任务卡片

**Files:**
- Create: `frontend/src/App.vue`
- Create: `frontend/src/components/StatusBar.vue`
- Create: `frontend/src/components/FilterTabs.vue`
- Create: `frontend/src/components/TaskCard.vue`
- Create: `frontend/src/components/TaskDetails.vue`
- Create: `frontend/tests/App.test.ts`

- [x] **Step 1: 编写卡片、筛选和监控操作失败测试**

测试：

- 默认选中“运行中”；
- “需处理”仅显示等待任务；
- 卡片展示项目和分支；
- 运行任务提供两种监控按钮；
- 已监控任务提供停止按钮；
- 点击详情展示安全摘要；
- SSE 更新替换对应卡片。

- [x] **Step 2: 运行失败测试**

Run: `cd frontend && npm test -- --run tests/App.test.ts`

Expected: FAIL。

- [x] **Step 3: 实现主页面组件**

使用语义化 HTML、键盘可操作按钮、可见焦点、状态不只依赖颜色。卡片在窄屏单列、宽屏自适应多列；不引入额外 UI 框架。

- [x] **Step 4: 实现 SSE 重连**

断线时显示连接状态，按指数间隔重连；重新连接后先拉取完整任务快照，再应用增量事件。

- [x] **Step 5: 运行组件测试**

Run: `cd frontend && npm test -- --run tests/App.test.ts`

Expected: PASS。

### Task 14：实现设置页和飞书测试交互

**Files:**
- Create: `frontend/src/components/SettingsPanel.vue`
- Create: `frontend/tests/SettingsPanel.test.ts`
- Modify: `frontend/src/App.vue`

- [x] **Step 1: 编写配置遮罩、保留密钥、清除密钥和端口提示失败测试**

```typescript
expect(screen.queryByDisplayValue("real-secret")).toBeNull()
expect(screen.getByLabelText("端口")).toHaveValue(6664)
```

同时测试保存请求携带 CSRF、显式清除开关、测试通知确认和错误展示。

- [x] **Step 2: 运行失败测试**

Run: `cd frontend && npm test -- --run tests/SettingsPanel.test.ts`

Expected: FAIL。

- [x] **Step 3: 实现设置面板**

保存后更新运行时可热更新项；端口或 host 变化时显示“执行 `codex-task-monitor restart` 后生效”。测试消息按钮需要二次确认并展示发送结果。

- [x] **Step 4: 运行设置测试**

Run: `cd frontend && npm test -- --run tests/SettingsPanel.test.ts`

Expected: PASS。

### Task 15：集成静态资源和 CLI 冒烟

**Files:**
- Modify: `codex_task_monitor/web/app.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Test: `tests/integration/test_web_api.py`

- [x] **Step 1: 编写首页静态资源失败测试**

验证 `/` 返回构建后的 `index.html`，未知前端路由回退到首页，`/api/*` 不被静态回退吞掉。

- [x] **Step 2: 运行失败测试**

Run: `.venv/bin/python -m pytest tests/integration/test_web_api.py -q`

Expected: FAIL 新增静态资源测试。

- [x] **Step 3: 挂载构建产物并声明包数据**

仅在构建目录存在时提供 UI；缺失时返回明确的构建提示。将静态资源包含进 Python 包配置。

- [x] **Step 4: 安装当前项目入口**

Run: `.venv/bin/python -m pip install -e .`

Expected: 安装成功，`.venv/bin/codex-task-monitor --help` 显示 `start/run/stop/restart`。

- [x] **Step 5: 验证后台生命周期**

Run: `.venv/bin/codex-task-monitor start`

Expected: 退出码 0，输出 `UI 地址：http://127.0.0.1:6664`。

Run: `curl -fsS http://127.0.0.1:6664/healthz`

Expected: 返回健康 JSON。

Run: `.venv/bin/codex-task-monitor restart`

Expected: 退出码 0，再次打印相同 UI 地址。

Run: `.venv/bin/codex-task-monitor stop`

Expected: 退出码 0，服务停止，PID 文件被清理。

### Task 16：文档、只读实机核验与完整验证

**Files:**
- Create: `README.md`
- Modify: `docs/superpowers/plans/2026-07-29-codex-task-monitor.md`

- [x] **Step 1: 编写 README**

覆盖：

- Python 和 Node 前置条件；
- 安装和前端构建；
- `config.yaml` 字段；
- 飞书应用机器人能力、发送消息权限、可用范围和 open_id；
- CLI 四个命令；
- UI 地址和端口修改；
- 数据目录、日志位置和密钥明文风险；
- 只读监控边界；
- 常见错误排查。

- [x] **Step 2: 运行 Python 全量测试和检查**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check . && .venv/bin/python -m mypy codex_task_monitor`

Expected: 全部 PASS。

- [x] **Step 3: 运行前端全量测试、类型检查和构建**

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run build`

Expected: 全部 PASS。

- [x] **Step 4: 执行只读 Codex 冒烟**

启动监控器后读取 `/api/tasks`，确认返回结构有效，且至少能够安全处理当前没有可发现运行任务的情况。检查测试和日志，确认没有调用 `thread/start`、`turn/start`、`turn/interrupt`、`thread/archive` 或 `thread/delete`。

- [x] **Step 5: 执行无头 UI 验收**

使用 Playwright 打开本地页面，检查：

- 默认端口和页面标题；
- 状态栏和四个筛选；
- 任务卡片或空状态；
- 设置页端口为 6664；
- 控制台无错误；
- 关闭页面和测试服务。

- [x] **Step 6: 检查敏感信息和代码注释**

Run: `rg -n '(app_secret:[[:space:]]*[^\"[:space:]]+|tenant_access_token|Authorization: Bearer|真实密钥)' . --glob '!frontend/node_modules/**' --glob '!data/**'`

Expected: 仅出现配置键名、测试占位符或文档说明，不出现真实密钥。人工抽查新增代码注释和 docstring，确认均为中文。

- [x] **Step 7: 更新计划完成状态并记录验证证据**

逐项勾选实际完成的步骤，记录最终测试数量、构建结果、CLI 冒烟结果和已知的跨 App Server 进程边界。不得执行 `git add`、`git commit` 或 `git push`。

## 实施验证记录

- 2026-07-29：Python 全量测试 `89 passed`；存在一条 FastAPI TestClient 上游弃用警告，无测试失败。
- 2026-07-29：Ruff 全项目检查通过；mypy 检查 30 个源文件通过。
- 2026-07-29：前端 Vitest `14 passed`；Vue TypeScript 类型检查通过；Vite 生产构建通过。
- 2026-07-29：`npm audit --omit=dev` 返回 0 个生产依赖漏洞。开发测试工具链存在由 `@vue/test-utils` 间接引入、当前无安全升级路径的审计项，不进入生产构建依赖。
- 2026-07-29：真实执行 `start → restart → /healthz → stop`，默认地址均为 `http://127.0.0.1:6664`；App Server 和本地会话观察器均连接；停止后运行状态文件已清理。
- 2026-07-29：无头页面验收确认页面标题、四个筛选、任务项目与分支、设置端口 6664、密钥空白投影和实时状态；浏览器控制台 0 错误、0 警告。
- 2026-07-29：实机发现并修复 App Server 超过 64 KiB 的 JSONL 行问题，新增大响应回归测试；同时过滤超过配置时间窗的陈旧会话状态。
- 2026-07-29：敏感信息扫描未发现真实密钥；`config.yaml`、SQLite 和日志权限为 `0600`，数据目录为 `0700`。
- 验证期间没有发送真实飞书消息，没有修改真实 Codex 任务，也没有执行任何 Git 写操作。
