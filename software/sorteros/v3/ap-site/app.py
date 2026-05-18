"""
sorteros AP captive portal — on-device FastAPI app.

Runs as root (port 80) via systemd, only when /var/lib/sorteros/wifi-configured
is absent. Brings up the AP via sorteros-ap-up.sh (the systemd unit's
ExecStartPre), serves the setup page, and tears down the AP via
sorteros-ap-down.sh after a successful Wi-Fi join.

This is the *brief* on-device UI between flashing and Wi-Fi joining. The
real sorter UI is the SvelteKit app at software/sorter/frontend/.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SCRIPT_DIR = Path(__file__).resolve().parent
log = logging.getLogger("sorteros-ap")

app = FastAPI()
if (SCRIPT_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=SCRIPT_DIR / "static"), name="static")


class ConnectRequest(BaseModel):
    ssid: str
    password: str


def _index_html() -> str:
    return (SCRIPT_DIR / "templates" / "index.html").read_text()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _index_html()


# Captive-portal probe URLs. Returning HTML (not what the probe expects)
# triggers the OS to pop the captive-portal browser pointed at us.
@app.get("/hotspot-detect.html", response_class=HTMLResponse)
@app.get("/generate_204", response_class=HTMLResponse)
@app.get("/connecttest.txt", response_class=HTMLResponse)
@app.get("/ncsi.txt", response_class=HTMLResponse)
def captive_probe() -> str:
    return _index_html()


@app.get("/api/networks")
def networks() -> list[dict]:
    """Scan for nearby Wi-Fi networks via nmcli. Best-effort; if nmcli
    isn't available (dev on a Mac), return an empty list rather than
    erroring — the UI handles empty gracefully."""
    try:
        out = subprocess.check_output(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("nmcli scan failed: %s", e)
        return []

    seen: set[str] = set()
    nets: list[dict] = []
    for line in out.splitlines():
        # SSID:SIGNAL:SECURITY — SSID can contain escaped colons; -t mode
        # uses ':' separator with backslash-escape for embedded colons.
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid = parts[0].replace("\\:", ":")
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            signal = int(parts[1])
        except ValueError:
            signal = 0
        security = parts[2] or "open"
        nets.append({"ssid": ssid, "signal": signal, "security": security})
    nets.sort(key=lambda n: n["signal"], reverse=True)
    return nets


@app.post("/api/connect")
def connect(req: ConnectRequest) -> JSONResponse:
    """Write an NM connection, bring down the AP, bring the new
    connection up. The AP teardown stamps /var/lib/sorteros/wifi-configured,
    which prevents sorteros-ap.service from coming back on reboot."""

    if not req.ssid:
        raise HTTPException(status_code=400, detail="ssid required")

    # Add the connection. nmcli is idempotent enough — if it already
    # exists we delete first.
    subprocess.run(
        ["nmcli", "connection", "delete", req.ssid],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    add_cmd = [
        "nmcli", "device", "wifi", "connect", req.ssid,
        "password", req.password,
        "ifname", "wlan0",
    ]
    try:
        subprocess.check_output(add_cmd, stderr=subprocess.STDOUT, timeout=30)
    except subprocess.CalledProcessError as e:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": e.output.decode("utf-8", "replace")[:500]},
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"ok": False, "error": "nmcli timed out"},
        )

    # Tear down the AP. The captive-portal session will die on the next
    # response so we fire-and-forget.
    subprocess.Popen(["/usr/local/sbin/sorteros-ap-down.sh"])
    return JSONResponse(content={"ok": True, "ssid": req.ssid})
