#!/usr/bin/env bash
# Runs ONCE on the freshly flashed SD card on first boot, via
# sorteros-firstboot.service. After completion it disables itself.
#
# Responsibilities:
#   - regenerate SSH host keys (if scrub deleted them)
#   - recreate /swapfile (scrub removed it to shrink the image)
#   - expand the rootfs partition to fill the SD card
#     (most Pi vendor images do this automatically; we add a safety net)
#   - mark setup complete
#
# Things this DOES NOT do (user does these manually after first boot):
#   - tailscale up           (optional — see README.md)
#   - write software/.env    (with OPENROUTER_API_KEY etc.)
#   - write software/machine.toml + software/mine/

set -euo pipefail

STAMP=/var/lib/sorteros/firstboot-done
mkdir -p "$(dirname "$STAMP")"

if [[ -f $STAMP ]]; then
    echo "firstboot already ran; exiting"
    exit 0
fi

log() { echo "[sorteros-firstboot] $*"; }

# --- SSH host keys ---
if ! ls /etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
    log "regenerating SSH host keys"
    ssh-keygen -A
    systemctl restart ssh || systemctl restart sshd || true
fi

# --- swapfile ---
if [[ ! -f /swapfile ]] && grep -q "^/swapfile" /etc/fstab; then
    log "recreating /swapfile (8 GB)"
    fallocate -l 8G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=8192 status=progress
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
fi

# --- rootfs grow (safety net) ---
# Orange Pi's stock first-run normally resizes for us, but if we baked
# our own image with pishrink the FS will be minimal. growpart + resize2fs.
ROOT_DEV=$(findmnt -no SOURCE /)
ROOT_DISK=$(lsblk -no PKNAME "$ROOT_DEV" | head -1)
PART_NUM=$(echo "$ROOT_DEV" | grep -oE '[0-9]+$')
if command -v growpart >/dev/null 2>&1 && [[ -n $ROOT_DISK && -n $PART_NUM ]]; then
    log "growing /dev/$ROOT_DISK partition $PART_NUM"
    growpart "/dev/$ROOT_DISK" "$PART_NUM" || true
    resize2fs "$ROOT_DEV" || true
fi

# --- heavy deps: uv sync + pnpm install (skipped during chroot build) ---
# Only runs when the v2.x build pipeline shipped the repo + toolchain but
# left the heavy native-arch deps unmaterialized. Detected by presence of
# the repo and absence of the .venv.
SOFTWARE_DIR=/home/orangepi/sorter-v2/software
if [[ -d "$SOFTWARE_DIR/sorter/backend" && ! -d "$SOFTWARE_DIR/sorter/backend/.venv" ]]; then
    log "running uv sync (first-boot, native arch) — this can take 10–15 min"
    su - orangepi -c "cd $SOFTWARE_DIR/sorter/backend && uv sync" || \
        log "WARN: uv sync failed; backend service will not start until resolved"
fi
if [[ -d "$SOFTWARE_DIR/sorter/frontend" && ! -d "$SOFTWARE_DIR/sorter/frontend/node_modules" ]]; then
    log "running pnpm install (first-boot, native arch)"
    su - orangepi -c "cd $SOFTWARE_DIR/sorter/frontend && pnpm install --frozen-lockfile" || \
        log "WARN: pnpm install failed; ui service will not start until resolved"
fi

touch "$STAMP"
log "done"
systemctl disable sorteros-firstboot.service || true
