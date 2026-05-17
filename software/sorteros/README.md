# SorterOS image bundling

Scripts for turning a working Orange Pi 5 install into a flashable SD-card
image we can put on a different Pi. Internal testing only — see the
hard-stop in `sorter-v2-agent-notes/orange_pi/update_strategy.md` before
publishing anything.

## Pipeline

```
[dev Pi, running] --(1)--> [dev Pi, cleaned but still running]
                              |
                              v
                          (2) power down, pull eMMC
                              |
                              v
                          [raw .img on workstation]
                              |
                              v
                          (3) shrink + scrub
                              |
                              v
                          [sorteros-<date>.img.zst]
                              |
                              v
                          (4) flash to fresh SD
                              |
                              v
                          [new Pi boots, first-boot script runs]
```

Steps:

1. **`prep-image.sh`** — runs on the dev Pi *while it's running*. Drops
   caches, junk, and the swapfile so the image-to-be is small. Idempotent
   and non-destructive to anything we care about (uv re-downloads, swap
   regenerates).
2. **Clone the eMMC** — must be done *offline* (power Pi down, read the
   eMMC from another machine). `dd` of a live rootfs is inconsistent.
   See `capture.md` for the procedure.
3. **`scrub.sh`** — runs against the captured `.img` on a workstation
   (loop-mounted). Removes secrets, host identity, ssh host keys,
   tailscale state, journal logs, bash history. Then `pishrink.sh` to
   minimize the partition.
4. **Flash + first boot** — write the scrubbed `.img.zst` to a new SD
   card. On first boot, `firstboot.service` (installed by `prep-image.sh`)
   regenerates SSH host keys, recreates `/swapfile`, and waits for the
   user to drop in a `software/.env` + `software/machine.toml`.

## Target

- **Card:** 32 GB SD (default). Should work down to 8 GB after shrink.
- **Compressed image size:** projected 1.5–2 GB zstd.
- **Used disk on flashed card before first boot:** ~5 GB.
- **Used disk on flashed card after first boot:** ~13 GB (swapfile back,
  user re-runs `uv sync` if a fresh venv is wanted).

Current dev Pi (2026-05-17): 24 GB used / 29 GB. Recoverable: 10.8 GB of
uv caches + 8 GB swapfile + 0.5 GB apt = ~19 GB.

## Tailscale policy

Tailscale is **installed by default** but **not started**. The flashed
card boots into a state where `tailscale` is on the system but
`tailscaled.service` is left enabled-but-unconfigured. The user can:

- Just use the machine over LAN (default). The backend listens on
  `0.0.0.0:8000` and the UI on `0.0.0.0:5173`; the user finds the Pi's
  IP on their local network.
- `sudo tailscale up` if they want remote access via the tailnet. Their
  own account, not ours — the previous machine's node key is scrubbed.

## Files

- `prep-image.sh` — run on the Pi. Cleans caches, installs the
  first-boot service. Safe to re-run.
- `scrub.sh` — run on a workstation against a mounted image. Removes
  secrets, identity, logs. Destructive — only run on a *captured image*,
  never on a live Pi.
- `firstboot.sh` + `sorteros-firstboot.service` — installed by
  `prep-image.sh`, runs once on the new Pi.
- `capture.md` — manual offline-clone procedure (`dd`, shrink, compress).
- `scrub-paths.txt` — canonical list of paths the scrub removes. Keep
  in sync with `scrub.sh`.
