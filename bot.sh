#!/usr/bin/env bash
# Lightweight nohup+pidfile wrapper. For a systemd setup use ./deploy.sh instead.
set -e

cd "$(dirname "$0")"

PIDFILE=".pid"
LOGFILE="logs/bot.log"
PYBIN=".venv/bin/python"

mkdir -p logs data

if [ ! -x "$PYBIN" ]; then
    PYBIN="$(command -v python3 || command -v python)"
    if [ -z "$PYBIN" ]; then
        echo "No python interpreter found. Run ./setup.sh first."
        exit 1
    fi
fi

is_running() {
    [ -f "$PIDFILE" ] || return 1
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null
}

case "${1:-}" in
    start)
        if is_running; then
            echo "Already running (PID $(cat "$PIDFILE"))."
            exit 0
        fi
        nohup "$PYBIN" main.py >> "$LOGFILE" 2>&1 &
        echo $! > "$PIDFILE"
        sleep 1
        if is_running; then
            echo "Started (PID $(cat "$PIDFILE")). Tail logs: ./bot.sh logs"
        else
            echo "Failed to start — check $LOGFILE"
            exit 1
        fi
        ;;
    stop)
        if ! is_running; then
            echo "Not running."
            rm -f "$PIDFILE"
            exit 0
        fi
        target_pid="$(cat "$PIDFILE")"
        echo "Stopping PID $target_pid..."
        kill "$target_pid" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$target_pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$target_pid" 2>/dev/null; then
            kill -9 "$target_pid" 2>/dev/null || true
        fi
        rm -f "$PIDFILE"
        echo "Stopped."
        ;;
    restart)
        "$0" stop || true
        "$0" start
        ;;
    status)
        if is_running; then
            echo "Running (PID $(cat "$PIDFILE"))."
        else
            echo "Not running."
        fi
        ;;
    logs)
        touch "$LOGFILE"
        tail -n 200 -f "$LOGFILE"
        ;;
    update)
        echo "Pulling code..."
        git pull --ff-only || true
        if [ -x ".venv/bin/pip" ]; then
            .venv/bin/pip install -r requirements.txt
        fi
        if command -v aerich >/dev/null 2>&1 && [ -x ".venv/bin/aerich" ]; then
            .venv/bin/aerich upgrade || true
        fi
        "$0" restart
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|update}"
        exit 1
        ;;
esac
