#!/bin/bash
# BBDown Mobile — 云服务器启动脚本
# 修改下面的占位符后运行: ./start-server.sh

set -e

# ===== 环境变量（修改这里）=====
export ADMIN_USERNAME="<管理员用户名>"
export ADMIN_PASSWORD="<管理员密码>"
export APP_SESSION_SECRET="<随机字符串，至少32字符>"
export SECRET_TOKEN="<与 Worker 约定的一致>"
export PORT="5001"
# =============================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")/bbdown_mobile"
PID_FILE="$PROJECT_DIR/.server.pid"
LOG_FILE="$PROJECT_DIR/server.log"

# 检查是否已修改
if [[ "$ADMIN_USERNAME" == *"<"* ]]; then
    echo "❌ 请先编辑此脚本，修改环境变量占位符"
    echo "   nano $0"
    exit 1
fi

# 检查是否已经在运行
if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "⚠️  服务器已在运行 (PID: $(cat "$PID_FILE"))"
    echo "如需重启请先执行: ./stop.sh"
    exit 1
fi

cd "$PROJECT_DIR"

echo "🚀 启动 BBDown 云服务器..."
nohup uv run python app.py >> "$LOG_FILE" 2>&1 &
PID=$!
echo $PID > "$PID_FILE"

sleep 2

if kill -0 $PID 2>/dev/null; then
    echo "✅ 服务器已启动 (PID: $PID)"
    echo "   日志: $LOG_FILE"
    echo "   停止: $(dirname "$SCRIPT_DIR")/deploy/stop.sh"
else
    echo "❌ 启动失败，查看日志: $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

