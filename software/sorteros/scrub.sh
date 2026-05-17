#!/usr/bin/env bash
# Mount a captured raw image (.img) and remove secrets + host identity.
# Run on a workstation (Linux preferred; macOS needs ext4 support which
# is annoying — use a Linux VM or Docker).
#
# DO NOT run this against a live root filesystem. It is destructive.
#
# Usage:
#   sudo ./scrub.sh /path/to/sorter-emmc-raw.img
#
# Outputs:
#   - mutates the image in place
#   - prints a summary of what was removed
#
# After this, run pishrink.sh to minimize the partition before zstd-ing.

set -euo pipefail

IMG=${1:-}
if [[ -z $IMG || ! -f $IMG ]]; then
    echo "usage: sudo $0 <path-to-image.img>" >&2
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PATHS_FILE="$SCRIPT_DIR/scrub-paths.txt"
if [[ ! -f $PATHS_FILE ]]; then
    echo "missing $PATHS_FILE" >&2
    exit 1
fi

log() { echo "[scrub] $*"; }

LOOP=$(losetup --show -fP "$IMG")
trap 'umount "$MNT" 2>/dev/null || true; losetup -d "$LOOP" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true' EXIT

# Find the partition. Stock Orange Pi image is a single partition (p1).
PART="${LOOP}p1"
if [[ ! -b $PART ]]; then
    echo "expected $PART but it does not exist; partition table differs from assumption" >&2
    lsblk "$LOOP"
    exit 1
fi

MNT=$(mktemp -d)
mount "$PART" "$MNT"
log "mounted $PART at $MNT"

removed=0
emptied=0

while IFS= read -r line; do
    [[ -z $line || $line == \#* ]] && continue
    case "$line" in
        :empty:*)
            target="$MNT/${line#:empty:}"
            if [[ -f $target ]]; then
                : > "$target"
                emptied=$((emptied + 1))
                log "emptied: ${line#:empty:}"
            fi
            ;;
        */)
            target="$MNT/${line%/}"
            if [[ -d $target ]]; then
                # contents only, keep the directory
                find "$target" -mindepth 1 -delete
                removed=$((removed + 1))
                log "wiped contents: $line"
            fi
            ;;
        *)
            target="$MNT/$line"
            if [[ -e $target ]]; then
                rm -rf "$target"
                removed=$((removed + 1))
                log "removed: $line"
            fi
            ;;
    esac
done < "$PATHS_FILE"

# Set a generic hostname so the new machine doesn't masquerade as the old.
echo "sorter" > "$MNT/etc/hostname"
# Replace old hostname in /etc/hosts (Ubuntu line: `127.0.1.1 orangepi5`).
sed -i 's/^\(127\.0\.1\.1\s\+\).*/\1sorter/' "$MNT/etc/hosts" || true

# Confirm machine.toml symlink still points at sorter-config (it does;
# we removed the target, not the link). User drops a fresh one in.
log "summary: $removed removed, $emptied emptied"
log "next: pishrink.sh \"$IMG\" && zstd -19 \"$IMG\""

sync
umount "$MNT"
losetup -d "$LOOP"
rmdir "$MNT"
trap - EXIT
