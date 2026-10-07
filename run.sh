#!/usr/bin/env bash
# 智能域名生成器 - 一键启动脚本
# 用法： ./run.sh
# 首次运行会自动创建 .venv 并安装依赖

set -e
cd "$(dirname "$0")"

VENV_DIR=".venv"
PY="python3"

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

# 4. 启动 Flask
echo "==> 启动服务，访问 http://127.0.0.1:5000/"
exec python app.py
