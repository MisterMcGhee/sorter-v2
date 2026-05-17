#!/usr/bin/env bash
# Synthetic test harness for scrub.sh.
# Creates a 64 MB ext4 image, populates it with dummy versions of every
# path listed in scrub-paths.txt, runs scrub.sh, and verifies the paths
# were removed/emptied.
#
# Must run on Linux (needs losetup + ext4). Run as root.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root" >&2
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PATHS_FILE="$SCRIPT_DIR/scrub-paths.txt"
WORK=$(mktemp -d)
IMG="$WORK/test.img"

cleanup() {
    umount "$WORK/mnt" 2>/dev/null || true
    [[ -n ${LOOP:-} ]] && losetup -d "$LOOP" 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "[test-scrub] building 64 MB image at $IMG"
truncate -s 64M "$IMG"
mkfs.ext4 -q -F "$IMG"
LOOP=$(losetup --show -fP "$IMG")
mkdir -p "$WORK/mnt"
mount "$LOOP" "$WORK/mnt"

# Repartition the test image so the layout matches what scrub.sh expects:
# scrub.sh assumes /dev/loopXp1 (a partitioned image). For test we'll
# accept either /dev/loopX or /dev/loopXp1 — easier to test with an
# unpartitioned image, but scrub.sh has the p1 hardcoded. So let's
# rebuild as partitioned.
umount "$WORK/mnt"
losetup -d "$LOOP"

echo "[test-scrub] rebuilding as partitioned image"
truncate -s 96M "$IMG"
parted -s "$IMG" mklabel msdos
parted -s "$IMG" mkpart primary ext4 1MiB 100%
LOOP=$(losetup --show -fP "$IMG")
sleep 1
mkfs.ext4 -q -F "${LOOP}p1"
mount "${LOOP}p1" "$WORK/mnt"

MNT="$WORK/mnt"

# Stamp dummy versions of every path in scrub-paths.txt
echo "[test-scrub] populating dummy paths"
while IFS= read -r line; do
    [[ -z $line || $line == \#* ]] && continue
    case "$line" in
        :empty:*)
            target="$MNT/${line#:empty:}"
            mkdir -p "$(dirname "$target")"
            echo "should-be-emptied" > "$target"
            ;;
        */)
            target="$MNT/${line%/}"
            mkdir -p "$target"
            echo "secret" > "$target/decoy-file"
            ;;
        *)
            target="$MNT/$line"
            mkdir -p "$(dirname "$target")"
            echo "secret" > "$target"
            ;;
    esac
done < "$PATHS_FILE"

# Make sure scrub.sh's hostname rewrite has something to chew on
mkdir -p "$MNT/etc"
echo "orangepi5" > "$MNT/etc/hostname"
echo "127.0.1.1 orangepi5" > "$MNT/etc/hosts"

# Unmount before invoking scrub.sh — it does its own losetup/mount.
umount "$MNT"
losetup -d "$LOOP"
LOOP=""

echo "[test-scrub] running scrub.sh"
"$SCRIPT_DIR/scrub.sh" "$IMG"

# Re-mount and verify
echo "[test-scrub] verifying"
LOOP=$(losetup --show -fP "$IMG")
sleep 1
mount "${LOOP}p1" "$WORK/mnt"

fail=0
while IFS= read -r line; do
    [[ -z $line || $line == \#* ]] && continue
    case "$line" in
        :empty:*)
            target="$MNT/${line#:empty:}"
            if [[ -f $target && ! -s $target ]]; then
                : # OK, empty
            else
                echo "FAIL: $line should be empty file"
                fail=$((fail + 1))
            fi
            ;;
        */)
            target="$MNT/${line%/}"
            if [[ -d $target ]] && [[ -z $(ls -A "$target") ]]; then
                : # OK, empty dir
            else
                echo "FAIL: $line should be empty directory"
                fail=$((fail + 1))
            fi
            ;;
        *)
            target="$MNT/$line"
            if [[ ! -e $target ]]; then
                : # OK, gone
            else
                echo "FAIL: $line should not exist"
                fail=$((fail + 1))
            fi
            ;;
    esac
done < "$PATHS_FILE"

# Hostname check
if [[ $(cat "$MNT/etc/hostname") == "sorter" ]]; then
    echo "OK: /etc/hostname rewritten to 'sorter'"
else
    echo "FAIL: /etc/hostname is $(cat "$MNT/etc/hostname"), expected 'sorter'"
    fail=$((fail + 1))
fi

if grep -q "127.0.1.1 sorter" "$MNT/etc/hosts"; then
    echo "OK: /etc/hosts rewritten"
else
    echo "FAIL: /etc/hosts not rewritten correctly"
    echo "  contents: $(cat "$MNT/etc/hosts")"
    fail=$((fail + 1))
fi

if [[ $fail -eq 0 ]]; then
    echo "[test-scrub] PASS"
    exit 0
else
    echo "[test-scrub] $fail failures"
    exit 1
fi
