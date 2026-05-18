#!/usr/bin/env bash
# Offline pre-flash validation of a SorterOS .img.
#
# Catches the "I burned 30 minutes flashing an image that never reaches
# the green LED" failure mode by inspecting everything u-boot needs
# before booti can run.
#
# Runs on Hive (or any Linux box with losetup + mount + parted). Reads
# the image read-only via loop devices.
#
# Usage:
#   sudo ./validate.sh <image.img>
#
# Exit code: 0 if all checks PASS, 1 if any FAIL. WARN doesn't fail.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (needs losetup/mount)" >&2
    exit 1
fi

IMG="${1:-}"
if [[ -z "$IMG" || ! -f "$IMG" ]]; then
    echo "usage: $0 <image.img>" >&2
    exit 1
fi

BASE_IMG="${SORTEROS_BASE_IMG:-/basically/sorteros/base/Orangepi5_1.2.2_ubuntu_jammy_server_linux6.1.99.img}"

PASS=0; FAIL=0; WARN=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; PASS=$((PASS+1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; WARN=$((WARN+1)); }
info() { printf '  \033[36minfo\033[0m %s\n' "$*"; }
hdr()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

LOOP=""
MNT_FAT=""
MNT_EXT4=""
cleanup() {
    set +e
    [[ -n "$MNT_FAT"  ]] && umount "$MNT_FAT"  2>/dev/null && rmdir "$MNT_FAT"
    [[ -n "$MNT_EXT4" ]] && umount "$MNT_EXT4" 2>/dev/null && rmdir "$MNT_EXT4"
    [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null
}
trap cleanup EXIT

echo "validating: $IMG"
echo "size: $(du -h "$IMG" | awk '{print $1}')"

# ─── 1. Bootloader region (sectors 64..16384) preserved from base ───
hdr "1. Rockchip bootloader region (sectors 64..16384)"
if [[ -f "$BASE_IMG" ]]; then
    BASE_HASH=$(dd if="$BASE_IMG" bs=512 skip=64 count=16320 status=none 2>/dev/null | sha256sum | awk '{print $1}')
    IMG_HASH=$(dd  if="$IMG"      bs=512 skip=64 count=16320 status=none 2>/dev/null | sha256sum | awk '{print $1}')
    info "base sha256: $BASE_HASH"
    info "img  sha256: $IMG_HASH"
    if [[ "$BASE_HASH" == "$IMG_HASH" ]]; then
        pass "bootloader region byte-identical to base image (SPL+u-boot intact)"
    else
        fail "bootloader region DIVERGED from base — Rockchip SPL/u-boot may be clobbered"
    fi
else
    warn "base image not found at $BASE_IMG; skipping SPL byte-compare"
    SECTOR64_NONZERO=$(dd if="$IMG" bs=512 skip=64 count=1 status=none 2>/dev/null | od -An -tx1 | tr -d ' \n' | grep -c -v '^0*$' || true)
    if [[ "$SECTOR64_NONZERO" -gt 0 ]]; then
        pass "sector 64 nonzero (Rockchip idbloader likely present)"
    else
        fail "sector 64 is all zeros — Rockchip idbloader missing"
    fi
fi

# ─── 2. Partition table ───
hdr "2. Partition table"
PT_OUT=$(sfdisk -d "$IMG" 2>/dev/null)
info "$(echo "$PT_OUT" | grep -E '^/|label:')"
P1_START=$(echo "$PT_OUT" | awk -F'[=, ]+' '/img1/ {for(i=1;i<=NF;i++)if($i=="start"){print $(i+1);exit}}')
P1_TYPE=$( echo "$PT_OUT" | awk -F'[=, ]+' '/img1/ {for(i=1;i<=NF;i++)if($i=="type") {print $(i+1);exit}}')
P2_START=$(echo "$PT_OUT" | awk -F'[=, ]+' '/img2/ {for(i=1;i<=NF;i++)if($i=="start"){print $(i+1);exit}}')
P2_TYPE=$( echo "$PT_OUT" | awk -F'[=, ]+' '/img2/ {for(i=1;i<=NF;i++)if($i=="type") {print $(i+1);exit}}')

# Expected v2.5+ layout: p1 FAT (type c) at sector 61440 (30 MiB),
#                       p2 ext4 (type 83) at sector 585728 (286 MiB).
[[ "$P1_START" == "61440" ]] && pass "p1 starts at sector 61440 (30 MiB)" || fail "p1 starts at $P1_START, expected 61440"
[[ "$P1_TYPE"  == "c"     ]] && pass "p1 type=c (FAT32 LBA)"                || fail "p1 type=$P1_TYPE, expected c"
[[ "$P2_START" == "585728" ]] && pass "p2 starts at sector 585728 (286 MiB)" || fail "p2 starts at $P2_START, expected 585728"
[[ "$P2_TYPE"  == "83"    ]] && pass "p2 type=83 (Linux)"                    || fail "p2 type=$P2_TYPE, expected 83"

# Refuse to continue if partition table is unworkable
if [[ -z "$P1_START" || -z "$P2_START" ]]; then
    fail "cannot parse partition table; aborting deeper checks"
    echo
    echo "summary: PASS=$PASS FAIL=$FAIL WARN=$WARN"
    exit 1
fi

# ─── attach loop + mount ───
LOOP=$(losetup --show -fP "$IMG")
sleep 1
[[ -b "${LOOP}p1" ]] || { fail "${LOOP}p1 didn't appear"; exit 1; }
[[ -b "${LOOP}p2" ]] || { fail "${LOOP}p2 didn't appear"; exit 1; }

MNT_FAT=$(mktemp -d /tmp/sorteros-validate-fat.XXXXXX)
MNT_EXT4=$(mktemp -d /tmp/sorteros-validate-ext4.XXXXXX)
mount -o ro "${LOOP}p1" "$MNT_FAT"
mount -o ro "${LOOP}p2" "$MNT_EXT4"

# ─── 3. FAT (p1): boot files u-boot needs ───
hdr "3. FAT p1 boot files (the bootable partition)"
info "p1 contents: $(ls "$MNT_FAT" | tr '\n' ' ')"

# Orange Pi 5 vendor boot.cmd loads from the partition u-boot found
# boot.scr on, with ${prefix} = "/boot/" or "/" depending on layout.
# For a separate boot partition, files live at the root of FAT.
# For a single-partition rootfs, files live at /boot/. The harness
# requires at least ONE valid layout to work.
HAS_BOOT_AT_ROOT=0
HAS_BOOT_AT_BOOT=0
for f in boot.scr Image uInitrd orangepiEnv.txt; do
    [[ -f "$MNT_FAT/$f" ]] && HAS_BOOT_AT_ROOT=$((HAS_BOOT_AT_ROOT+1))
    [[ -f "$MNT_FAT/boot/$f" ]] && HAS_BOOT_AT_BOOT=$((HAS_BOOT_AT_BOOT+1))
done

if [[ $HAS_BOOT_AT_ROOT -ge 3 ]]; then
    pass "FAT root has boot.scr/Image/uInitrd/orangepiEnv.txt"
    FAT_HAS_KERNEL=1
elif [[ $HAS_BOOT_AT_BOOT -ge 3 ]]; then
    pass "FAT /boot/ has boot.scr/Image/uInitrd/orangepiEnv.txt"
    FAT_HAS_KERNEL=1
else
    fail "FAT partition has NO kernel/boot.scr — u-boot will not find a bootable kernel on p1"
    info "  (this is the v2.5 boot failure: u-boot's scan_dev_for_boot finds the FAT first; if it has no boot.scr, boot dies)"
    FAT_HAS_KERNEL=0
fi

# DTB presence — needed regardless of root/boot layout
if [[ -d "$MNT_FAT/dtb/rockchip" ]]; then
    pass "FAT has dtb/rockchip/"
elif [[ -d "$MNT_FAT/boot/dtb/rockchip" ]]; then
    pass "FAT has /boot/dtb/rockchip/"
elif [[ $FAT_HAS_KERNEL == 1 ]]; then
    fail "FAT has kernel but no dtb/rockchip directory — overlay loads will fail"
fi

# ─── 4. ext4 (p2): rootfs /boot/ completeness ───
hdr "4. ext4 p2 /boot/ contents"
BOOT_DIR="$MNT_EXT4/boot"
if [[ ! -d "$BOOT_DIR" ]]; then
    fail "no /boot/ on ext4 rootfs"
else
    for f in boot.scr Image uInitrd orangepiEnv.txt; do
        if [[ -f "$BOOT_DIR/$f" ]]; then
            pass "ext4 /boot/$f present"
        else
            fail "ext4 /boot/$f missing"
        fi
    done
    if [[ -d "$BOOT_DIR/dtb/rockchip" ]]; then
        pass "ext4 /boot/dtb/rockchip/ present"
    else
        fail "ext4 /boot/dtb/rockchip/ missing"
    fi
fi

# ─── 5. orangepiEnv.txt sanity ───
hdr "5. orangepiEnv.txt"
ENV_FILE=""
for cand in "$MNT_FAT/orangepiEnv.txt" "$MNT_FAT/boot/orangepiEnv.txt" "$BOOT_DIR/orangepiEnv.txt"; do
    [[ -f "$cand" ]] && ENV_FILE="$cand" && break
done
if [[ -z "$ENV_FILE" ]]; then
    fail "no orangepiEnv.txt anywhere"
else
    info "using: $ENV_FILE"
    cat "$ENV_FILE" | sed 's/^/    /'
    grep -q '^overlays=.*wifi-ap6275p' "$ENV_FILE" \
        && pass "AP6275P overlay enabled in orangepiEnv.txt" \
        || fail "overlays= line does not include wifi-ap6275p (Wi-Fi will not work)"
    grep -q '^fdtfile=' "$ENV_FILE" \
        && pass "fdtfile= set" \
        || fail "fdtfile= missing"
    ROOTDEV=$(awk -F= '/^rootdev=/ {print $2}' "$ENV_FILE" || true)
    [[ -n "$ROOTDEV" ]] && info "rootdev=$ROOTDEV"
fi

# ─── 6. AP6275P overlay .dtbo exists where boot.cmd looks for it ───
hdr "6. AP6275P overlay .dtbo file"
OVERLAY_NAME="rk3588-wifi-ap6275p.dtbo"
FOUND_OVERLAY=""
for cand in \
    "$MNT_FAT/dtb/rockchip/overlay/$OVERLAY_NAME" \
    "$MNT_FAT/boot/dtb/rockchip/overlay/$OVERLAY_NAME" \
    "$BOOT_DIR/dtb/rockchip/overlay/$OVERLAY_NAME" ; do
    [[ -f "$cand" ]] && FOUND_OVERLAY="$cand" && break
done
if [[ -n "$FOUND_OVERLAY" ]]; then
    pass "overlay file found: ${FOUND_OVERLAY#$MNT_EXT4}${FOUND_OVERLAY#$MNT_FAT}"
else
    fail "$OVERLAY_NAME not found on either partition (Wi-Fi won't come up even with overlays= set)"
fi

# ─── 7. fstab consistency ───
hdr "7. /etc/fstab"
if [[ -f "$MNT_EXT4/etc/fstab" ]]; then
    cat "$MNT_EXT4/etc/fstab" | grep -vE '^\s*#|^\s*$' | sed 's/^/    /'
    P2_UUID=$(blkid -s UUID -o value "${LOOP}p2" 2>/dev/null || true)
    info "actual p2 UUID: $P2_UUID"
    if [[ -n "$P2_UUID" ]]; then
        grep -q "UUID=$P2_UUID.*\s/\s" "$MNT_EXT4/etc/fstab" \
            && pass "fstab root entry UUID matches actual p2 UUID" \
            || fail "fstab root entry UUID does NOT match p2 UUID ($P2_UUID)"
    fi
    P1_LABEL=$(blkid -s LABEL -o value "${LOOP}p1" 2>/dev/null || true)
    info "actual p1 LABEL: $P1_LABEL"
    if [[ -n "$P1_LABEL" ]]; then
        grep -q "LABEL=$P1_LABEL" "$MNT_EXT4/etc/fstab" \
            && pass "fstab system-boot entry LABEL matches p1 LABEL" \
            || warn "fstab does not reference LABEL=$P1_LABEL (cloud-init mount may fail)"
    fi
else
    fail "no /etc/fstab on rootfs"
fi

# ─── 8. systemd units (sorteros-*) installed + enabled ───
hdr "8. sorteros-* systemd units"
EXPECTED_UNITS=(
    sorteros-firstboot-fast.service
    sorteros-firstboot-deps.service
    sorteros-growfs.service
    sorteros-apply-network-config.service
)
for u in "${EXPECTED_UNITS[@]}"; do
    if [[ -f "$MNT_EXT4/etc/systemd/system/$u" ]]; then
        pass "$u installed"
    else
        fail "$u MISSING"
    fi
done
# Optional: tailscale auto-up
if [[ -f "$MNT_EXT4/etc/systemd/system/sorteros-tailscale-up.service" ]]; then
    pass "sorteros-tailscale-up.service present (Tailscale auto-join wired)"
else
    warn "sorteros-tailscale-up.service absent (image built without TAILSCALE_AUTH_KEY)"
fi

# ─── 9. NetworkManager fallback connections ───
hdr "9. NetworkManager fallback connections"
NM_DIR="$MNT_EXT4/etc/NetworkManager/system-connections"
for conn in spencer-hotspot.nmconnection sorteros-eth-fallback.nmconnection; do
    if [[ -f "$NM_DIR/$conn" ]]; then
        pass "$conn present"
    else
        warn "$conn missing (won't break boot, but reduces reachability)"
    fi
done

# ─── summary ───
hdr "summary"
printf "  PASS: %d\n  FAIL: %d\n  WARN: %d\n" "$PASS" "$FAIL" "$WARN"
echo
if [[ $FAIL -gt 0 ]]; then
    echo "VERDICT: image will likely fail to boot. Fix the FAIL items above."
    exit 1
else
    echo "VERDICT: image passes all hard checks. Hardware-test recommended."
    exit 0
fi
