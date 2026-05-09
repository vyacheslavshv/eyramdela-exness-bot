#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SERVICE_FILE="/etc/systemd/system/${PROJECT_NAME}.service"

echo "Project:  $PROJECT_NAME"
echo "Path:     $PROJECT_DIR"
echo ""

# If service already exists — update mode
if systemctl list-unit-files --no-pager | grep -q "^${PROJECT_NAME}.service"; then
    echo "Service exists. Updating..."

    cd "$PROJECT_DIR"
    git pull
    source .venv/bin/activate
    pip install -r requirements.txt
    aerich upgrade

    systemctl restart "$PROJECT_NAME"

    echo ""
    echo "Updated and restarted $PROJECT_NAME."
    echo "  systemctl status $PROJECT_NAME"
    echo "  journalctl -u $PROJECT_NAME -f"
    exit 0
fi

# Fresh deploy
echo "Creating service..."

if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "Error: .venv not found. Run ./setup.sh first."
    exit 1
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=${PROJECT_NAME}
After=network.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/main.py

Restart=on-failure
RestartSec=10
TimeoutStopSec=180
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$PROJECT_NAME"
systemctl restart "$PROJECT_NAME"

echo ""
echo "Service $PROJECT_NAME created and started."
echo "  systemctl status $PROJECT_NAME"
echo "  journalctl -u $PROJECT_NAME -f"
