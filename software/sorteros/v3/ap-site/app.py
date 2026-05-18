"""
sorteros AP captive portal.

Runs on the Pi when no Wi-Fi is configured. Serves a 1-page setup UI
that lists nearby Wi-Fi networks, takes the user's SSID + password,
writes an NM connection, tears down the AP, joins the chosen network.

This is on-device and lightweight on purpose: FastAPI + vanilla JS,
Tailwind via CDN. No build step. The sorter's main UI (SvelteKit) lives
elsewhere; this is the brief moment between flashing and Wi-Fi joining.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SCRIPT_DIR = Path(__file__).resolve().parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=SCRIPT_DIR / "static"), name="static")


class ConnectRequest(BaseModel):
    ssid: str
    password: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (SCRIPT_DIR / "templates" / "index.html").read_text()


# Common captive-portal probe paths — iOS / Android / Windows / Chrome.
# Returning HTML (not the expected probe response) triggers the phone to
# open a captive-portal browser pointed at us.
@app.get("/hotspot-detect.html", response_class=HTMLResponse)
@app.get("/generate_204", response_class=HTMLResponse)
@app.get("/connecttest.txt", response_class=HTMLResponse)
@app.get("/ncsi.txt", response_class=HTMLResponse)
def captive_probe() -> str:
    return index()


@app.get("/api/networks")
def networks() -> list[dict]:
    # TODO: nmcli -t -f SSID,SIGNAL,SECURITY device wifi list
    return []


@app.post("/api/connect")
def connect(req: ConnectRequest) -> dict:
    # TODO:
    # 1. nmcli connection add type wifi con-name <ssid> ssid <ssid>
    #    wifi-sec.key-mgmt wpa-psk wifi-sec.psk <password>
    # 2. systemctl start sorteros-ap-down.service
    #    (the service stops hostapd/dnsmasq and `nmcli connection up <ssid>`)
    _ = subprocess  # placeholder for the actual nmcli invocations
    return {"ok": True, "ssid": req.ssid}
