#!/usr/bin/env bash

set -Eeuo pipefail

repository_url="https://github.com/DhWU-coder/codex-task-monitor.git"
repository_ssh_url="git@github.com:DhWU-coder/codex-task-monitor.git"
task_user_home="${HOME:?无法确定用户主目录}"
install_directory="${CODEX_TASK_MONITOR_INSTALL_DIR:-${task_user_home}/.local/share/codex-task-monitor}"
binary_directory="${CODEX_TASK_MONITOR_BIN_DIR:-${task_user_home}/.local/bin}"
python_command="${CODEX_TASK_MONITOR_PYTHON:-python3}"
cli_link="${binary_directory}/codex-task-monitor"
remote_mode=false
dry_run=false

show_help() {
    cat <<'EOF'
用法：bash install.sh [选项]

选项：
  --remote   强制使用远程安装模式
  --dry-run  只显示安装计划，不修改文件
  -h, --help 显示帮助
EOF
}

fail() {
    printf '错误：%s\n' "$1" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "缺少命令：$1"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)
            remote_mode=true
            ;;
        --dry-run)
            dry_run=true
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            fail "未知选项：$1"
            ;;
    esac
    shift
done

# 只有磁盘上的脚本旁边存在完整项目文件时，才判定为本地仓库模式。
script_source="${BASH_SOURCE[0]-}"
local_source_directory=""
if [[ "$remote_mode" == false && -n "$script_source" && -f "$script_source" ]]; then
    script_directory="$(cd "$(dirname "$script_source")" && pwd -P)"
    if [[ -f "${script_directory}/pyproject.toml" && -f "${script_directory}/frontend/package.json" ]]; then
        local_source_directory="$script_directory"
    fi
fi

if [[ -n "$local_source_directory" ]]; then
    install_mode="本地仓库"
    source_directory="$local_source_directory"
else
    install_mode="远程安装"
    source_directory="$install_directory"
    remote_mode=true
fi

printf 'Codex 任务监控器安装\n'
printf '安装模式：%s\n' "$install_mode"
printf '仓库地址：%s\n' "$repository_url"
printf '源码目录：%s\n' "$source_directory"
printf '全局命令：%s\n' "$cli_link"

# 安装前先保护用户已有的同名普通文件或目录。
if [[ -e "$cli_link" && ! -L "$cli_link" ]]; then
    fail "拒绝覆盖已有的普通文件或目录：${cli_link}"
fi

if [[ "$dry_run" == true ]]; then
    printf '预演完成：将创建虚拟环境、安装项目、构建前端并创建全局命令链接。\n'
    exit 0
fi

if [[ "$remote_mode" == true ]]; then
    require_command git

    if [[ -e "$source_directory" ]]; then
        [[ -d "${source_directory}/.git" ]] || fail "远程安装目录已存在，但不是 Git 仓库：${source_directory}"
        current_origin="$(git -C "$source_directory" remote get-url origin 2>/dev/null || true)"
        if [[ "$current_origin" != "$repository_url" && "$current_origin" != "$repository_ssh_url" ]]; then
            fail "远程安装目录属于其他仓库：${current_origin:-未配置 origin}"
        fi
        [[ -z "$(git -C "$source_directory" status --porcelain)" ]] || fail "远程安装目录存在未提交改动，请先处理：${source_directory}"
        printf '正在更新远程仓库……\n'
        git -C "$source_directory" fetch origin main
        git -C "$source_directory" switch main
        git -C "$source_directory" merge --ff-only origin/main
    else
        printf '正在下载远程仓库……\n'
        mkdir -p "$(dirname "$source_directory")"
        git clone --branch main --single-branch "$repository_url" "$source_directory"
    fi
fi

[[ -f "${source_directory}/pyproject.toml" ]] || fail "源码目录缺少 pyproject.toml：${source_directory}"
[[ -f "${source_directory}/frontend/package-lock.json" ]] || fail "源码目录缺少前端锁文件：${source_directory}"

require_command "$python_command"
require_command node
require_command npm

if ! "$python_command" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
    fail "需要 Python 3.12 或更高版本，当前命令：${python_command}"
fi

node_major_version="$(node --version | sed 's/^v//' | cut -d. -f1)"
if [[ ! "$node_major_version" =~ ^[0-9]+$ ]] || (( node_major_version < 20 )); then
    fail "需要 Node.js 20 或更高版本"
fi

printf '正在准备 Python 虚拟环境……\n'
if [[ ! -x "${source_directory}/.venv/bin/python" ]]; then
    "$python_command" -m venv "${source_directory}/.venv"
fi

if ! "${source_directory}/.venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
    fail "现有 .venv 的 Python 版本低于 3.12，请移走该虚拟环境后重试"
fi

printf '正在安装 Python 项目……\n'
"${source_directory}/.venv/bin/python" -m pip install -e "$source_directory"

printf '正在安装并构建前端……\n'
(
    cd "${source_directory}/frontend"
    npm ci
    npm run build
)

cli_target="${source_directory}/.venv/bin/codex-task-monitor"
[[ -x "$cli_target" ]] || fail "CLI 安装结果不存在：${cli_target}"

printf '正在创建全局命令……\n'
mkdir -p "$binary_directory"
temporary_link="${binary_directory}/.codex-task-monitor-link.$$"
ln -s "$cli_target" "$temporary_link"
mv -f "$temporary_link" "$cli_link"

"$cli_link" --help >/dev/null

printf '\n安装完成。\n'
printf '启动命令：codex-task-monitor start\n'
printf '默认 UI：http://127.0.0.1:6664\n'

case ":${PATH:-}:" in
    *":${binary_directory}:"*)
        ;;
    *)
        printf '\n提示：%s 当前不在 PATH 中，请把下面一行加入 ~/.zshrc 或 ~/.bashrc：\n' "$binary_directory"
        printf 'export PATH="%s:$PATH"\n' "$binary_directory"
        ;;
esac
