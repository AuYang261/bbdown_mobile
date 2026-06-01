#!/bin/bash
# BBDown Mobile — 停止脚本（云服务器 + Worker）
# 用法: ./stop.sh          # 停止本机所有 BBDown 进程
#       ./stop.sh server   # 仅停止云服务器
#       ./stop.sh worker   # 仅停止 Worker

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_PID_FILE="$PROJECT_DIR/bbdown_mobile/.server.pid"
WORKER_PID_FILE="$PROJECT_DIR/worker/.worker.pid"

stop_pid_file() {
    local pid_file="$1"
    local name="$2"
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "⏳ 停止 $name (PID: $pid)..."
            kill "$pid"
            # 等最多 10 秒
            for i in $(seq 1 10); do
                kill -0 "$pid" 2>/dev/null || break
                sleep 1
            done
            # 还没死就强杀
            if kill -0 "$pid" 2>/dev/null; then
                echo "   强制终止..."
                kill -9 "$pid" 2>/dev/null || true
            fi
            echo "✅ $name 已停止"
        else
            echo "   $name 进程不存在 (PID: $pid)"
        fi
        rm -f "$pid_file"
    fi
}

stop_port() {
    local port="$1"
    local pids=$(lsof -ti:$port 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "⏳ 清理端口 $port ..."
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 1
        echo "$pids" | xargs kill -9 2>/dev/null || true
        echo "✅ 端口 $port 已释放"
    fi
}

case "${1:-all}" in
    server)
        stop_pid_file "$SERVER_PID_FILE" "云服务器"
        stop_port 5001
        ;;
    worker)
        stop_pid_file "$WORKER_PID_FILE" "Worker"
        ;;
    all)
        echo "🛑 停止所有 BBDown 服务..."
        stop_pid_file "$SERVER_PID_FILE" "云服务器"
        stop_pid_file "$WORKER_PID_FILE" "Worker"
        stop_port 5001
        echo "✅ 全部已停止"
        ;;
    *)
        echo "用法: $0 [server|worker|all]"
        exit 1
        ;;
esac
