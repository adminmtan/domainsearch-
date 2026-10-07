#!/usr/bin/env bash
# 智能域名生成器 - 一键启动脚本
# 用法： ./run.sh [--port N]
# 默认端口 5001（macOS 系统服务 ControlCenter 默认占用 5000）

set -e
cd "$(dirname "$0")"

VENV_DIR=".venv"
PY="python3"
PORT="5001"

# 解析参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    --help|-h)
      echo "Usage: ./run.sh [--port N]"
      exit 0;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

# 1. 创建虚拟环境（仅首次）
if [ ! -d "$VENV_DIR" ]; then
  echo "==> 创建虚拟环境 $VENV_DIR ..."
  $PY -m venv "$VENV_DIR"
fi

# 2. 激活虚拟环境
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# 3. 安装依赖（依赖未变则 pip 会跳过）
echo "==> 安装/更新依赖 ..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

# 4. 检测端口是否被占
check_port() {
  local p="$1"
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    local owner
    owner="$(lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1}')"
    echo "❌ 端口 $p 被进程 [$owner] 占用。请换端口启动：./run.sh --port 5050" >&2
    return 1
  fi
  return 0
}

if ! check_port "$PORT"; then
  exit 1
fi

# 5. 启动 Flask
echo "==> 启动服务，访问 http://127.0.0.1:$PORT/"
exec env PORT="$PORT" python app.py