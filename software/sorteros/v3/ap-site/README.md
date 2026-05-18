# sorteros AP captive portal

Tiny web app that runs on the Pi when no Wi-Fi is configured. Pi brings up
its own AP (`sorter-setup-XXXX`), user joins from their phone, captive
portal pops up automatically, user picks a Wi-Fi from a list, types
password, submits, done.

## Design rules

Even though this is on-device and not the main UI, **follow the sorter
frontend's design rules** so the visual language is consistent across the
brand:

- Sharp edges. No `rounded-*` utilities (exception: spinner).
- No left-accent borders. Flat 1px borders on all four sides.
- `text-sm` minimum for any body copy.
- No raw hex; use `@theme` tokens (mirror the palette from
  `software/sorter/frontend/src/routes/layout.css`).

Reference: `software/sorter/frontend/CLAUDE.md`.

This site only ever runs from a phone, on the Pi's own AP, so it can be
1-page, dead simple, no router. But it should *feel* like a basically
product when the user lands on it — that's the whole point of brand
consistency on first impression.

## Implementation plan

- **FastAPI** for the backend (same stack as sorter backend; small).
- **Single HTML page** served at `/`, with vanilla JS for the network
  scan + submit. No build step. Tailwind via CDN is OK here (this is
  on-device and small; no point in a SvelteKit pipeline).
- Endpoints:
  - `GET /` — render the page.
  - `GET /api/networks` — `nmcli -t -f SSID,SIGNAL,SECURITY device wifi list`.
  - `POST /api/connect` — body `{ssid, password}`, writes an NM
    connection, returns 200. The systemd watcher tears down the AP and
    `nmcli connection up <id>` joins the chosen network.
- The teardown logic lives in `/usr/local/sbin/sorteros-ap-down.sh`
  (installed by the build overlay).

## DNS / captive portal mechanics

iOS and Android probe specific URLs to detect captive portals:
- iOS: `captive.apple.com/hotspot-detect.html` (expects exact "Success"
  body)
- Android: `connectivitycheck.gstatic.com/generate_204` (expects 204)

`dnsmasq` is configured to resolve **every** name to the Pi's IP
(wildcard `address=/#/192.168.4.1`). When the phone probes, it gets the
Pi back, which doesn't respond with the expected probe response → phone
shows a captive-portal notification, opens an in-app browser to the
URL it probed → that URL resolves to us → we serve `/` → user sees the
setup page.

## Status

- 2026-05-17: scaffolded only — `app.py` skeleton, no real handlers yet.
- First milestone: get the page to render in Spencer's phone browser
  after joining the Pi's AP. No real `nmcli` integration needed for
  that first test.
