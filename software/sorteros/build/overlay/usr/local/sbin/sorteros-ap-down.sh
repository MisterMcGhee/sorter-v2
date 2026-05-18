#!/usr/bin/env bash
# Tear down the SorterOS setup AP. Called by the systemd unit's ExecStopPost
# (when the service is stopped after the user has submitted their Wi-Fi)
# and also directly by the captive portal app after a successful connect.

set -euo pipefail

echo "[sorteros-ap-down] tearing down AP"

nmcli connection down sorteros-ap 2>/dev/null || true
nmcli connection delete sorteros-ap 2>/dev/null || true

# Drop a stamp so sorteros-ap.service's ConditionPathExists prevents it
# from coming back up on reboot.
mkdir -p /var/lib/sorteros
touch /var/lib/sorteros/wifi-configured

echo "[sorteros-ap-down] done"
