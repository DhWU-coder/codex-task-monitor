# Codex 任务监控器

这是一个只在本机运行的 Codex 任务看板。它聚合 Codex App Server
和本地会话文件中的任务状态，让你选择“监控当前轮次”或“持续监控”，并在任务完成、失败、中断、等待输入或等待审批时向指定飞书账号发送私聊消息。

默认 UI 地址：

```text
http://127.0.0.1:6664
```

## 功能

- 展示本机可发现的 Codex Desktop、CLI、IDE 和 App Server 任务。
- 卡片展示任务标题、项目名、工作目录、Git 分支、状态、时长和最近摘要。
- 提供“运行中”“需处理”“最近结束”“全部”四种筛选。
- 只允许对当前仍在运行或等待处理的任务启动监控。
- 支持当前轮次监控和同一任务后续轮次的持续监控。
- 向一个预先配置的飞书账号发送幂等文本通知。
- 使用 `config.yaml` 和 UI 设置页管理端口、飞书与通知开关。
- 使用太阳/月亮按钮切换浅色与深色主题；首次跟随系统，手动选择后保存在当前浏览器。
- 提供 `start`、`run`、`stop`、`restart` 四个 CLI 命令。

## 环境要求

- Python 3.12 或更高版本
- 已安装并能执行的 `codex` CLI
- Node.js 20 或更高版本，仅在首次构建或修改前端时需要

## 安装

### 远程一行安装

本机尚未下载仓库时，执行：

```bash
curl -fsSL https://raw.githubusercontent.com/DhWU-coder/codex-task-monitor/main/install.sh | bash
```

脚本默认把源码安装到 `~/.local/share/codex-task-monitor`，并在
`~/.local/bin/codex-task-monitor` 创建全局命令链接。以后重复执行同一条命令会安全更新已有安装；如果安装目录有未提交改动，脚本会停止而不会覆盖这些改动。

### 已下载仓库后一键安装

进入仓库根目录执行：

```bash
bash install.sh
```

这种方式直接安装当前仓库代码，全局命令会指向当前仓库的 `.venv`。两种安装方式都会创建或复用虚拟环境、安装 Python 项目、按锁文件安装前端依赖并构建 UI，无需执行 `source .venv/bin/activate`。

安装完成后可从任意目录启动：

```bash
codex-task-monitor start
```

命令会打印实际 UI 地址。如果 `~/.local/bin` 尚未加入 `PATH`，安装脚本会打印需要加入 `~/.zshrc` 或 `~/.bashrc` 的配置行。

### 手动安装

需要逐步排查安装问题时，可在项目目录中执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cd frontend
npm ci
npm run build
cd ..
```

安装完成后，命令入口位于 `.venv/bin/codex-task-monitor`。激活虚拟环境后也可以直接使用 `codex-task-monitor`。

### 手动创建全局 CLI

一键安装脚本已经自动完成这一步。仅在手动安装时，可把虚拟环境中的入口链接到用户级 PATH：

```bash
mkdir -p ~/.local/bin
ln -s "$(pwd)/.venv/bin/codex-task-monitor" ~/.local/bin/codex-task-monitor
```

确认 `~/.local/bin` 已加入 PATH：

```bash
echo "$PATH"
command -v codex-task-monitor
codex-task-monitor --help
```

如果 PATH 中没有该目录，可在 `~/.zshrc` 或 `~/.bashrc` 中加入：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

完成后，无需执行 `source .venv/bin/activate`，可以从任意目录运行：

```bash
codex-task-monitor start
```

全局入口仍使用项目自己的 `.venv` 和源码，因此不会污染系统 Python。移动或删除项目目录后，需要重新运行安装脚本或手动创建链接。

## CLI

后台启动，与 `start` 完全等价：

```bash
codex-task-monitor run
```

后台启动，与 `run` 完全等价：

```bash
codex-task-monitor start
```

停止后台服务：

```bash
codex-task-monitor stop
```

重启后台服务：

```bash
codex-task-monitor restart
```

`run` 和 `start` 都会在健康检查通过后返回终端并打印实际 UI 地址。两者都是幂等命令，服务已经运行时不会创建第二个进程。`restart` 会重启后台服务并打印新地址。

## 配置

默认配置文件是项目根目录的 `config.yaml`。也可以通过环境变量指定另一个稳定路径：

```bash
export CODEX_TASK_MONITOR_CONFIG=/absolute/path/to/config.yaml
```

完整默认配置：

```yaml
server:
  host: 127.0.0.1
  port: 6664

codex:
  command: codex
  refresh_interval_seconds: 2
  reconcile_interval_seconds: 30
  recent_completed_hours: 24
  orphaned_running_timeout_minutes: 60

feishu:
  app_id: ""
  app_secret: ""
  receive_id: ""
  receive_id_type: email

notifications:
  enabled: true
  summary_max_length: 500
  notify_completed: true
  notify_failed: true
  notify_interrupted: true
  notify_waiting_input: true
  notify_waiting_approval: true
```

配置说明：

- `server.host` 只允许 `127.0.0.1`、`localhost` 或 `::1`。
- `server.port` 默认是 `6664`。修改 host 或端口后需要执行 `codex-task-monitor restart`。
- `codex.command` 是本机 Codex CLI 命令，通常保持 `codex`。
- `recent_completed_hours` 控制看板保留非活动任务的时间窗口。
- `orphaned_running_timeout_minutes` 默认是 `60`。只有 App Server 返回 `notLoaded`，且本地会话仍停在活动状态并超过该时长没有新记录时，任务才会按中断处理；后续出现新会话事件会恢复。
- `app_secret` 在 UI 中不会回显。UI 留空会保留已有密钥，只有勾选“清除已保存密钥”才会删除。
- 飞书与通知开关保存后立即热更新，无需重启。

## 飞书配置

首版使用飞书自建应用机器人向一个账号发送私聊消息：

1. 在[飞书开放平台](https://open.feishu.cn/app)创建企业自建应用。
2. 为应用启用机器人能力。
3. 申请发送消息所需权限，并确保应用可用范围包含接收账号。
4. 取得应用的 App ID 和 App Secret。
5. 推荐在 UI 中选择 `email`，并填写接收人在当前飞书租户中的企业邮箱。
6. 在 UI 设置页或 `config.yaml` 中填写配置并保存。
7. 在设置页点击“发送测试消息”，确认后验证私聊是否到达。

如需使用 ID，也可以选择 `open_id`、`union_id` 或 `user_id` 并填写匹配的值。`open_id` 与具体飞书应用绑定，同一个用户在不同应用中的 `open_id` 可能不同，必须使用当前 App ID 对应的值。已有配置会保留原接收人类型，不会自动改成邮箱。

飞书鉴权使用租户访问令牌，发送接口使用飞书消息 API。权限名和审批流程可能随飞书开放平台调整，应以[飞书服务端 API 文档](https://open.feishu.cn/document/server-docs/im-v1/message/create)为准。

## 数据与安全边界

应用只监听回环地址，不提供远程访问能力。Web 层校验 Host、同源请求和 CSRF Token，不启用跨域访问。

以下文件位于有效配置文件同级的 `data` 目录：

- `monitor.db`：监控选择、通知幂等记录和安全任务快照
- `runtime.json`：后台服务 PID 与运行元数据
- `codex-task-monitor.log`：后台日志

配置文件、SQLite、运行状态和日志在 POSIX 系统上使用 `0600` 权限，数据目录使用 `0700`。

`app_secret` 以明文保存在 `config.yaml` 中。不要把真实配置提交到版本控制，不要把配置文件或日志发给不受信任的人。

## 只读监控原则

监控器不会调用 Codex 的任务创建、启动、打断、归档或删除接口。官方 App Server 查询使用只读状态数据库模式；本地会话观察器只读取已有 JSONL 文件，不修改 Codex 会话。

App Server 只能直接观察其自身可见的状态边界，因此应用同时使用本地会话观察器补足其他 Codex Desktop 和 CLI 进程。数据源断开、未知状态或监控器离线不会被推断为“任务完成”。

重启后只恢复仍在运行或等待处理的监控记录。监控器离线期间已经结束的任务不会补发通知。

## 开发验证

后端：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy codex_task_monitor
```

前端：

```bash
cd frontend
npm test -- --run
npm run typecheck
npm run build
npm audit --omit=dev
```

## 常见问题

### 启动提示端口被占用

修改 `config.yaml` 的 `server.port`，然后执行：

```bash
codex-task-monitor restart
```

### 页面没有任务

先确认本机存在正在运行的 Codex 任务，再查看 `data/codex-task-monitor.log` 和 `/healthz`。即使 App Server 暂时不可用，本地会话观察器仍会继续提供可发现任务。

### 飞书测试消息失败

依次检查 App ID、App Secret、接收人 ID 类型、应用机器人能力、发送消息权限和应用可用范围。API 返回的最终错误会显示在设置页，自动重试只处理网络、限流和服务端临时错误。

### 修改端口后页面地址没有变化

端口和监听地址不能在当前 Uvicorn 进程内热切换。保存配置后执行 `codex-task-monitor restart`，命令会打印新地址。
