#!/usr/bin/env bash
# 启动 yuming 前端服务（sandbox 友好，detach 到新进程组）
set -e
cd "$(dirname "$0")/.."

# 优先用 5001（默认），被占用则用 5555
for PORT in 5001 5555 7777; do
  if ! lsof -i:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  PORT=""
done

if [ -z "$PORT" ]; then
  echo "❌ 5001/5555/7777 都被占用"
  exit 1
fi

echo "🚀 启动 yuming (port $PORT)"
PORT=$PORT /usr/local/bin/python3 app.py &
PID=$!
echo "PID: $PID"
echo ""
echo "👉 在浏览器打开: http://127.0.0.1:$PORT/"
echo "🛑 停止: kill $PID"
echo ""

# 等 2 秒看是否存活
sleep 2
if kill -0 $PID 2>/dev/null; then
  echo "✅ 服务运行中"
  echo "$PID" > /tmp/yuming.pid
else
  echo "❌ 启动失败，看日志："
  tail -20 /tmp/yuming.log 2>/dev/null || echo "(无日志)"
  exit 1
fi
