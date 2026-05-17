# Offline eMMC capture procedure

The dev Pi runs from **eMMC** (`/dev/mmcblk1`, 29.1 GB), not an SD card.
Cloning a running rootfs with `dd` produces an inconsistent image — the
filesystem journal can be mid-write. So the capture step has to happen
with the rootfs **not mounted as `/`**.

Two ways to do this.

## Option 1 (recommended): boot the Pi off a USB stick, dd the eMMC

1. Flash an Orange Pi Ubuntu Jammy image (the same one originally used)
   to a USB stick. Boot the Pi from USB — Orange Pi 5 will prefer USB at
   boot if eMMC is unselected in the boot menu, or hold the maskrom
   button. Confirm with `lsblk` that `/` is on the USB device, not
   `mmcblk1`.
2. Plug a USB drive large enough for the image (≥ 30 GB free). Mount it.
3. Run:
   ```bash
   dd if=/dev/mmcblk1 of=/mnt/usb/sorter-emmc-raw.img bs=4M status=progress conv=fsync
   ```
   Takes 10–20 minutes depending on eMMC speed.
4. Power down, unplug USB drive, put eMMC back in its normal boot role,
   and bring up the dev Pi as usual. Carry the USB drive to the
   workstation.

## Option 2: shut the Pi down, remove the eMMC

The Orange Pi 5 eMMC is on a small daughterboard. Remove it, plug it
into a USB adapter (the kind that exposes eMMC as a block device), and
read it from any Linux workstation:

```bash
sudo dd if=/dev/sdX of=sorter-emmc-raw.img bs=4M status=progress conv=fsync
```

(Where `sdX` is whatever the adapter enumerates as — confirm with
`lsblk` before invoking dd.)

## After capture

```bash
# 1. Scrub secrets + host identity in place
sudo ./scrub.sh sorter-emmc-raw.img

# 2. Shrink the partition (pishrink works on any single-partition image)
#    Get it from https://github.com/Drewsif/PiShrink
sudo pishrink.sh sorter-emmc-raw.img

# 3. Compress
zstd -19 sorter-emmc-raw.img
# -> sorter-emmc-raw.img.zst, ~1.5–2 GB
```

## Flash

```bash
zstdcat sorter-emmc-raw.img.zst | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

Where `sdX` is the target SD card. pishrink leaves the FS at minimum
size and configures it to auto-expand on first boot (its standard
`/etc/rc.firstboot` shim); our `sorteros-firstboot.service` also
includes a `growpart + resize2fs` safety net for SD cards smaller than
expected or for the eMMC-restore case.

## Pre-flight before doing any of this

Confirm with Spencer first. Power-cycling the dev Pi will interrupt any
other agent's work on it.

Run `software/sorteros/prep-image.sh` on the dev Pi first (over SSH,
non-destructive) so the captured image is already small.
