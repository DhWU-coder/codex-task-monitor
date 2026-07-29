# 一键安装脚本实施计划

> **For implementation:** REQUIRED: Use superpowers:executing-plans to implement this plan in the current session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为远程用户和已经下载仓库的用户提供一条命令完成依赖安装、前端构建和全局 CLI 链接。

**Architecture:** 根目录 Bash 脚本负责识别本地或远程模式，并把两种入口汇入同一安装流程；pytest 通过隔离的临时目录和 `--dry-run` 验证模式、路径与覆盖保护；README 只暴露两条主安装命令，并保留手动安装作为故障排查入口。

**Tech Stack:** Bash、Git、Python venv/pip、npm、pytest。

**Design:** `docs/superpowers/specs/2026-07-29-one-line-installer-design.md`

---

## Chunk 1：安装器、文档与发布

### Task 1：以测试定义安装器行为

**Files:**
- Create: `tests/unit/test_installer.py`
- Test: `tests/unit/test_installer.py`

- [x] **Step 1: 编写本地模式失败测试**

测试从仓库根目录执行 `bash install.sh --dry-run`，并通过临时环境变量覆盖全局命令目录；断言脚本识别本地模式、输出真实仓库目录和预期链接路径。

- [x] **Step 2: 编写远程模式、覆盖保护和前端工作目录失败测试**

测试执行 `bash install.sh --remote --dry-run`，断言输出 GitHub 仓库地址和临时安装目录；在临时全局命令路径创建普通文件，断言脚本返回非零状态并输出拒绝覆盖提示；从仓库外执行隔离安装，断言 npm 的工作目录始终是目标 `frontend` 目录。

- [x] **Step 3: 运行测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/unit/test_installer.py -q`

Expected: FAIL，原因是根目录尚无 `install.sh`。

### Task 2：实现一键安装脚本

**Files:**
- Create: `install.sh`
- Test: `tests/unit/test_installer.py`

- [x] **Step 1: 实现参数、模式与路径解析**

支持自动本地模式、`--remote`、`--dry-run` 和三个环境变量覆盖项；所有代码注释使用中文。

- [x] **Step 2: 实现依赖校验和安全更新**

校验 Git、Python 版本和 npm；远程目录首次克隆，已有正确仓库只执行 fetch、切换主分支及仅快进合并；错误目录直接拒绝。

- [x] **Step 3: 实现统一安装、全局链接和结果提示**

创建 `.venv`、安装 Python 包、执行 `npm ci` 与前端构建；拒绝覆盖普通文件，创建或更新符号链接，验证 `--help`，提示 UI 启动命令和 PATH 配置。

- [x] **Step 4: 运行安装器测试和语法检查**

Run: `.venv/bin/python -m pytest tests/unit/test_installer.py -q && bash -n install.sh`

Expected: PASS，全部安装器测试通过且 Shell 语法无错误。

### Task 3：更新安装文档并完成验证

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-29-one-line-installer.md`

- [x] **Step 1: 更新 README**

在安装章节首先给出远程 `curl | bash` 命令和仓库内 `bash install.sh` 命令，说明默认安装位置、全局 CLI、PATH 提示和重复执行的更新行为；把原流程标为手动安装。

- [x] **Step 2: 运行完整验证**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS，全部后端测试通过。

Run: `.venv/bin/python -m ruff check . && .venv/bin/python -m mypy codex_task_monitor`

Expected: PASS，Python 静态检查通过。

Run: `npm --prefix frontend test -- --run && npm --prefix frontend run typecheck && npm --prefix frontend run build && npm --prefix frontend audit --omit=dev`

Expected: PASS，前端测试、类型检查、构建通过，生产依赖无已知漏洞。

- [x] **Step 3: 检查变更范围并提交**

按照 `~/.codex/git提交消息生成-prompt.md` 生成中文 Conventional Commit，确认提交只包含安装器、测试、README、设计和计划文档。

- [x] **Step 4: 推送并核验远程**

Run: `git push origin main`

Expected: 本地 `main` 与 `origin/main` 指向同一新提交，工作区干净。
