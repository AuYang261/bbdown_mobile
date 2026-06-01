#!/bin/bash
# BBDown Mobile — 内网 Worker 启动脚本
# 用法: ./start-worker.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKER_DIR="$(dirname "$SCRIPT_DIR")/worker"
PID_FILE="$WORKER_DIR/.worker.pid"
LOG_FILE="$WORKER_DIR/worker.log"

# 检查 CLOUD_URL 和 SECRET_TOKEN
if [ -z "$CLOUD_URL" ] || [ -z "$SECRET_TOKEN" ]; then
    echo "❌ 请先设置环境变量:"
    echo "   export CLOUD_URL=https://your-domain.com"
    echo "   export SECRET_TOKEN=<与云服务器一致>"
    echo "   export BBDOWN_BIN=/path/to/BBDown   # 可选"
    exit 1
fi

# 检查是否已经在运行
if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "⚠️  Worker 已在运行 (PID: $(cat "$PID_FILE"))"
    echo "如需重启请先执行: ./stop.sh"
    exit 1
fi

cd "$WORKER_DIR"

echo "🚀 启动 BBDown Worker..."
echo "   云端: $CLOUD_URL"
echo "   BBDown: ${BBDOWN_BIN:-BBDown}"

nohup uv run python worker.py >> "$LOG_FILE" 2>&1 &
PID=$!
echo $PID > "$PID_FILE"

sleep 2

if kill -0 $PID 2>/dev/null; then
    echo "✅ Worker 已启动 (PID: $PID)"
    echo "   日志: $LOG_FILE"
    echo "   停止: $(dirname "$SCRIPT_DIR")/deploy/stop.sh"
else
    echo "❌ 启动失败，查看日志: $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
