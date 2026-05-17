#!/usr/bin/env bash
# Run on the Pi (as root) to shrink the rootfs prior to cloning.
# Idempotent. Non-destructive to anything we actually need:
#   - uv caches: re-downloaded on next `uv sync`
#   - apt caches/lists: re-fetched on next `apt update`
#   - swapfile: recreated by sorteros-firstboot on first boot
#   - journal/logs: rotated away
#
# Does NOT remove:
#   - the backend .venv (already-built PyTorch etc.)
#   - the repo
#   - installed apt packages
#   - systemd units
#   - tailscale binary (just its state — see scrub.sh)
#
# Usage on the dev Pi:
#   ssh root-pi 'bash -s' < software/sorteros/prep-image.sh

set -euo pipefail

DRY_RUN=${DRY_RUN:-0}

if [[ $EUID -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
fi

if [[ $DRY_RUN == 1 ]]; then
    echo "[prep-image] DRY RUN: nothing will be deleted; reports sizes that would be reclaimed"
fi

log() { echo "[prep-image] $*"; }

# rm wrapper honoring DRY_RUN. In dry mode, sums up size and prints, no delete.
_dry_total=0
maybe_rm() {
    local path=$1
    if [[ ! -e $path && ! -L $path ]]; then
        return
    fi
    local sz
    sz=$(du -sb "$path" 2>/dev/null | awk '{print $1}') || sz=0
    if [[ $DRY_RUN == 1 ]]; then
        log "WOULD remove ($(numfmt --to=iec --suffix=B "$sz")): $path"
        _dry_total=$((_dry_total + sz))
    else
        log "removing ($(numfmt --to=iec --suffix=B "$sz")): $path"
        rm -rf "$path"
    fi
}

maybe_run() {
    if [[ $DRY_RUN == 1 ]]; then
        log "WOULD run: $*"
    else
        log "running: $*"
        "$@"
    fi
}

log "before:"
df -h / | tail -1

# --- uv caches ---
# uv installs hardlinks into the project venv; cache is download-only.
maybe_rm /home/orangepi/.cache/uv
maybe_rm /root/.cache/uv

# Spare Python interpreters uv might have downloaded. We pin 3.13.
for p in /home/orangepi/.local/share/uv/python/cpython-3.14.*-linux-aarch64-gnu \
         /root/.local/share/uv/python/cpython-3.14.*-linux-aarch64-gnu; do
    [[ -e $p ]] && maybe_rm "$p"
done

# --- apt ---
maybe_run apt-get clean
maybe_rm /var/lib/apt/lists

# --- pnpm store (if any) ---
for d in /home/orangepi/.local/share/pnpm/store /root/.local/share/pnpm/store \
         /home/orangepi/.cache/pnpm /root/.cache/pnpm; do
    [[ -e $d ]] && maybe_rm "$d"
done

# --- swapfile ---
# Listed in /etc/fstab with `pri=-2` and 8 GB size; firstboot.sh recreates
# it with the SAME 8 GB size to preserve total swap headroom (zram 7.8 GB +
# disk 8 GB ≈ 15 GB). Removing the zeros now is the single biggest size win.
if [[ -f /swapfile ]]; then
    if [[ $DRY_RUN == 1 ]]; then
        sz=$(du -sb /swapfile | awk '{print $1}')
        log "WOULD disable and remove /swapfile ($(numfmt --to=iec --suffix=B "$sz")); firstboot recreates at 8GB"
        _dry_total=$((_dry_total + sz))
    else
        log "disabling and removing /swapfile (will be recreated as 8GB on first boot)"
        swapoff /swapfile || true
        rm -f /swapfile
    fi
fi

# --- journal ---
maybe_run journalctl --rotate
maybe_run journalctl --vacuum-time=1s

# --- temp + crash + history ---
for p in /tmp /var/tmp /var/crash; do
    if [[ $DRY_RUN == 1 ]]; then
        sz=$(du -sb "$p" 2>/dev/null | awk '{print $1}') || sz=0
        log "WOULD wipe contents of $p ($(numfmt --to=iec --suffix=B "$sz"))"
        _dry_total=$((_dry_total + sz))
    else
        find "$p" -mindepth 1 -delete 2>/dev/null || true
    fi
done
for f in /root/.bash_history /home/orangepi/.bash_history; do
    [[ -f $f ]] && maybe_rm "$f"
done

# --- core dumps ---
maybe_rm /var/lib/systemd/coredump

# --- install first-boot unit ---
if [[ $DRY_RUN == 1 ]]; then
    log "WOULD install /usr/local/sbin/sorteros-firstboot.sh + /etc/systemd/system/sorteros-firstboot.service"
    log "WOULD systemctl enable sorteros-firstboot.service"
else
    log "installing sorteros-firstboot.service"
    install -m 0755 /home/orangepi/sorter-v2/software/sorteros/firstboot.sh \
        /usr/local/sbin/sorteros-firstboot.sh
    install -m 0644 /home/orangepi/sorter-v2/software/sorteros/sorteros-firstboot.service \
        /etc/systemd/system/sorteros-firstboot.service
    systemctl daemon-reload
    systemctl enable sorteros-firstboot.service
fi

# --- machine-id, ssh host keys, tailscale, .env are scrubbed OFF-Pi ---
# Do NOT do that here; this script runs on the live dev Pi and we don't
# want to break SSH access or tailnet membership.

log "after:"
df -h / | tail -1

if [[ $DRY_RUN == 1 ]]; then
    log "DRY RUN total reclaimable: $(numfmt --to=iec --suffix=B "$_dry_total")"
    log "(re-run without DRY_RUN=1 to actually apply)"
else
    log "done. next step: power down, pull eMMC, capture and scrub off-line."
    log "see software/sorteros/capture.md"
fi
