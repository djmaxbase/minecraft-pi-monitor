#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $EUID -eq 0 ]]; then
  echo 'Run this as your normal Pi user: bash install.sh (without sudo).'
  exit 1
fi
# Unit paths with spaces need escaping; keep install location simple.
if [[ ! "$APP_DIR" =~ ^/[a-zA-Z0-9_./-]+$ ]]; then
  echo 'Move the folder to a path without spaces/special characters, e.g. ~/Uitgeteld-Pi.'
  exit 1
fi
command -v sudo >/dev/null
sudo apt-get update
sudo apt-get install -y python3 dnsutils openssl
python3 -c 'import sys; assert sys.version_info >= (3,9), "Python 3.9+ required"'
sudo systemctl stop uitgeteld-monitor.service 2>/dev/null || true
mkdir -p "$APP_DIR/data"
if [[ ! -f "$APP_DIR/config.json" ]]; then
  cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
fi
cd "$APP_DIR"
python3 "$APP_DIR/app.py" --setup
sudo tee /etc/systemd/system/uitgeteld-monitor.service >/dev/null <<UNIT
[Unit]
Description=Minecraft Pi Monitor
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$(id -un)
Group=$(id -gn)
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/launcher.py
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-$APP_DIR/monitor.env
Restart=on-failure
RestartSec=5
TimeoutStopSec=25
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable uitgeteld-monitor
sudo systemctl restart uitgeteld-monitor
printf '\nReady. Open http://%s:8080\n' "$(hostname -I | awk '{print $1}')"
echo 'Status: sudo systemctl status uitgeteld-monitor'

if [[ -f "$APP_DIR/data/first-login.txt" ]]; then
  echo "Dashboard login (bewaar dit wachtwoord):"
  cat "$APP_DIR/data/first-login.txt"
fi
