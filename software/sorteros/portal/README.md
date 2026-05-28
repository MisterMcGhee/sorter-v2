# SorterOS Captive Portal

Zero-touch Wi-Fi onboarding for SorterOS images. Replaces the
`sorteros-setup/` Vercel customizer — the image ships generic, and the
user joins an AP on the device to configure Wi-Fi via a browser captive
portal.

Today this is a **spike**: backend + frontend run locally with no
hardware, no image-builder integration, no systemd unit. Once we're happy
with the UX we wire it into `build/overlay/` and add the AP-mode
orchestrator.

## Layout

```
portal/
├── README.md          # this file
├── backend/
│   ├── portal.py      # single-file FastAPI app (~400 LOC)
│   └── pyproject.toml # fastapi + uvicorn + pydantic
└── frontend/
    ├── package.json   # SvelteKit + adapter-static + Tailwind v4
    └── src/
        ├── lib/api.ts
        ├── lib/components/{SignalBars,HandoffPanel}.svelte
        └── routes/+page.svelte
```

## Run locally

Two terminals. Backend in mock mode (no `nmcli` calls):

```sh
cd backend
uv run --with fastapi --with uvicorn --with pydantic \
    python portal.py --mode mock --port 8088 --log-level info
```

Frontend with Vite dev (proxies `/api/*` to the backend on 8088):

```sh
cd frontend
pnpm install   # first time
pnpm dev
```

Open <http://localhost:5176>. You'll see a fake network list, can pick
one, the submit flow ends on the QR-code handoff screen.

To exercise the **production-style** build (static bundle served by the
backend directly, exactly how the image will work):

```sh
cd frontend && pnpm build
cd ../backend
uv run --with fastapi --with uvicorn --with pydantic \
    python portal.py --mode mock --port 8088 --static-dir ../frontend/build
```

Then hit <http://localhost:8088> — same UX, served from a single port,
identical to what the Orange Pi will do in AP mode.

## API contract

All routes the frontend uses:

| Method | Path               | Returns                                                                                |
| ------ | ------------------ | -------------------------------------------------------------------------------------- |
| GET    | `/api/status`      | `{ mode, hostname, suggested_url, configured, last_attempt }`                          |
| GET    | `/api/wifi-scan`   | `{ networks: [{ ssid, signal, security, in_use }], mocked }`                           |
| POST   | `/api/wifi-connect`| body `{ ssid, password?, hidden?, hostname?, sshKey? }` → `{ ok, next_url, hostname }` |

Captive-portal probe routes — all `302 → /` so the OS sheet pops the
portal automatically when the user joins the AP:

- `/hotspot-detect.html`, `/library/test/success.html` — iOS / macOS
- `/generate_204`, `/gen_204` — Android
- `/connecttest.txt`, `/ncsi.txt` — Windows
- `/canonical.html` — Firefox
- catch-all `/{anything}` — anything else still 302s

## Backend modes

```
--mode=auto   # ap if nmcli on PATH, else mock (default)
--mode=ap     # production on-device — real nmcli scan & connection writes
--mode=mock   # canned data, no system calls, safe for laptop dev
```

In `ap` mode `_nmcli_write_wifi` mirrors the format firstboot's existing
`stage_apply_config_toml` expects — same `.nmconnection` file shape so
the handoff to firstboot doesn't need any new logic.

When the connect endpoint succeeds, the backend:

1. writes `/etc/NetworkManager/system-connections/<SSID>.nmconnection`
2. writes `/etc/sorteros-config.toml` if the user provided a hostname or
   SSH key (same file firstboot already reads)
3. responds 200 to the frontend so the QR handoff page renders
4. waits 5 s, runs `nmcli connection up <SSID>` (30 s timeout)
5. on Layer-3 success: touches `/var/lib/sorteros/wifi-configured`
   (firstboot's gate file) and drops the AP profile
6. on failure: leaves the AP up so the user can retry with a fresh
   password

If the user cuts power between steps 1–6, firstboot at next boot will
still re-trigger the portal because the gate file is the last thing
written.

## What's mocked vs. real

| Path             | mock mode               | ap mode                                  |
| ---------------- | ----------------------- | ---------------------------------------- |
| Scan             | canned 5-entry list     | `nmcli dev wifi list --rescan yes`       |
| Connection write | no-op                   | writes `.nmconnection` + `nmcli reload`  |
| Switchover task  | flips `last_attempt=ok` | runs `nmcli connection up <SSID>`, gates |
| Hostname read    | local `gethostname()`   | local `gethostname()`                    |

## Not done yet (next PRs)

- **First-hardware-boot validation**: full end-to-end test on a fresh
  CM5 — flash → AP → smartphone captive-portal sheet → submit → handoff
  → firstboot stages → sorter-ui. Backend can be retuned (timeouts,
  switchover delay) based on what the real Wi-Fi chip does.
- **Reset-GPIO / factory-reset**: long-press handler that deletes
  `/var/lib/sorteros/wifi-configured` and reboots so the device falls
  back into AP mode without re-flashing.
- **Tailscale auth in portal**: optional field so a fresh image joins
  the org tailnet without ever touching SSH first. Already plumbed in
  `/etc/sorteros-config.toml` by firstboot's `stage_tailscale_up` —
  just needs the input on the portal form.
- **Hardened captive-portal probe responses**: today every probe gets a
  302, which works but logs as "captive portal" forever. A friendlier
  exit experience is to flip the probes to "success" responses once
  `wifi-configured` exists so devices on the AP don't get stuck loops.

## QR / mDNS handoff

The handoff screen renders the suggested URL (`http://<hostname>.local/`)
as a QR code so the user can re-enter the network and find the device
without typing anything. mDNS lookup works natively on iOS and macOS;
modern Chrome/Edge on Android resolve `.local` via Network Service
Discovery; on Windows the user needs Bonjour Print Services or to be on
a network with an mDNS-aware router. For the rare host that can't
resolve `.local`, follow-up work adds a `/api/last-seen` ping to
`setup.basically.website` so the device can be looked up by
human-readable LEGO name instead of by IP.
