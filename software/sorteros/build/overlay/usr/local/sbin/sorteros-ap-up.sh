#!/usr/bin/env bash
# Bring up the SorterOS setup AP.
#
# Strategy: let NetworkManager do the heavy lifting. `nmcli device wifi
# hotspot` creates an AP + DHCP + (NM's built-in) dnsmasq for clients.
# We then run uvicorn for the captive portal on port 80 (handled by the
# systemd unit's ExecStart, not here).
#
# The SSID is deterministic from the MAC suffix so multiple sorters can
# coexist visibly. Password is `sortersort` (printed on a sticker on the
# device; not a secret).

set -euo pipefail

SSID_PREFIX="sorter-setup"
PASSWORD="sortersort"
IFACE=wlan0

# 4-char MAC suffix uppercased, e.g. A3F2
MAC_SUFFIX=$(cat "/sys/class/net/$IFACE/address" | tr -d ':' | tail -c 5 | tr -d '\n' | tr a-z A-Z)
SSID="${SSID_PREFIX}-${MAC_SUFFIX}"

echo "[sorteros-ap-up] bringing up AP: $SSID"

# Make sure NM is in charge of wlan0 (some Orange Pi images mark it unmanaged).
nmcli device set "$IFACE" managed yes || true

# If the user previously connected to a Wi-Fi, this stamp file exists and we
# should bail. The systemd unit also has ConditionPathExists=!, but belt+braces.
if [[ -f /var/lib/sorteros/wifi-configured ]]; then
    echo "[sorteros-ap-up] wifi already configured; not starting AP"
    exit 0
fi

nmcli device wifi hotspot \
    ifname "$IFACE" \
    con-name sorteros-ap \
    ssid "$SSID" \
    password "$PASSWORD"

# Pin the AP's IPv4 so the captive portal has a stable address.
nmcli connection modify sorteros-ap ipv4.addresses 192.168.4.1/24 ipv4.method shared
nmcli connection up sorteros-ap || true

echo "[sorteros-ap-up] AP $SSID up at 192.168.4.1"
