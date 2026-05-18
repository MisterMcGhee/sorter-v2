#!/usr/bin/env bash
# Find an Orange Pi (or any Linux box) on a direct-ethernet link from this Mac
# and SSH into it. Works regardless of whether the Pi has DHCP/IPv4 — uses
# IPv6 link-local (always-on on Linux) discovered via the all-nodes multicast.
#
# Usage:
#   ./find-pi.sh              # discover and print SSH command
#   ./find-pi.sh ssh          # discover and exec ssh
#   ./find-pi.sh "<cmd>"      # discover and run remote command
#
# Default creds match the sorteros image: orangepi/orangepi.

set -u

USER_NAME=${PI_USER:-orangepi}
PASSWORD=${PI_PASS:-orangepi}
REMOTE_CMD=${1:-}

candidate_ifaces() {
  # Active en* interfaces that have an IPv6 link-local and look like wired
  # (en0 is wifi on most Macs; exclude it). Order: highest-numbered first
  # since USB-Ethernet dongles tend to be en4+.
  ifconfig -l | tr ' ' '\n' | grep -E '^en[1-9][0-9]*$' | sort -r | while read -r ifc; do
    if ifconfig "$ifc" 2>/dev/null | grep -q 'status: active' \
       && ifconfig "$ifc" 2>/dev/null | grep -q 'inet6 fe80'; then
      echo "$ifc"
    fi
  done
}

discover_on() {
  local ifc=$1
  local self
  self=$(ifconfig "$ifc" | awk '/inet6 fe80/ {sub(/%.*/,"",$2); print $2; exit}')
  # Two pings to populate NDP, then read neighbors.
  ping6 -c 2 -i 0.5 -W 1 -I "$ifc" ff02::1 >/dev/null 2>&1
  ndp -an 2>/dev/null | awk -v ifc="$ifc" -v self="$self" '
    $0 ~ ifc {
      addr=$1; sub(/%.*/,"",addr)
      if (addr != self && addr ~ /^fe80:/) print addr
    }
  ' | sort -u
}

try_ssh() {
  local ifc=$1 addr=$2 cmd=$3
  local target="${USER_NAME}@${addr}%${ifc}"
  if [ -n "$cmd" ]; then
    sshpass -p "$PASSWORD" ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
      -o PreferredAuthentications=password -o PubkeyAuthentication=no \
      -o NumberOfPasswordPrompts=1 "$target" "$cmd"
  else
    sshpass -p "$PASSWORD" ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
      -o PreferredAuthentications=password -o PubkeyAuthentication=no \
      -o NumberOfPasswordPrompts=1 "$target"
  fi
}

if ! command -v sshpass >/dev/null; then
  echo "sshpass not installed (brew install sshpass)" >&2
  exit 2
fi

for ifc in $(candidate_ifaces); do
  echo "==> scanning $ifc" >&2
  for addr in $(discover_on "$ifc"); do
    echo "    candidate ${addr}%${ifc}" >&2
    # Probe SSH banner first to filter out non-Pis (printers, etc.).
    if ! nc -G 2 -z "${addr}%${ifc}" 22 2>/dev/null; then
      continue
    fi
    case "$REMOTE_CMD" in
      ssh|"")
        if [ "$REMOTE_CMD" = ssh ]; then
          exec sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=accept-new \
            -o PreferredAuthentications=password -o PubkeyAuthentication=no \
            "${USER_NAME}@${addr}%${ifc}"
        fi
        host=$(try_ssh "$ifc" "$addr" 'hostname' 2>/dev/null)
        if [ -n "$host" ]; then
          echo "found: $host at ${addr}%${ifc}" >&2
          echo "ssh ${USER_NAME}@${addr}%${ifc}"
          exit 0
        fi
        ;;
      *)
        if try_ssh "$ifc" "$addr" "$REMOTE_CMD"; then exit 0; fi
        ;;
    esac
  done
done

echo "no Pi found on any direct-ethernet link" >&2
exit 1
