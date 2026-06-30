#!/usr/bin/env python3
"""Unified launcher for the LEGO Sorter (backend + frontend).

Designed to be run directly from PyCharm (right-click → Run) or from the
terminal:

    python run.py            # start both backend and frontend
    python run.py backend    # backend only
    python run.py frontend   # frontend only
    python run.py api        # API-only backend (no hardware controller)

The script manages both processes, color-codes their output, and shuts
everything down cleanly on Ctrl+C or when the PyCharm stop button is pressed.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "sorter" / "backend"
FRONTEND_DIR = ROOT / "sorter" / "frontend"
ENV_FILE = ROOT / ".env"

# ANSI color codes (work in PyCharm's Run console and most terminals)
GREEN = "\033[32m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

_shutting_down = threading.Event()
_processes: list[subprocess.Popen] = []
_lock = threading.Lock()


def log(msg: str) -> None:
    print(f"{DIM}[run]{RESET} {msg}", flush=True)


def _load_env() -> dict[str, str]:
    """Load the .env file into a dict merged with the current environment."""
    env = dict(os.environ)
    if ENV_FILE.is_file():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                line = line.removeprefix("export ")
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                env[key] = value
    return env


def _stream_output(proc: subprocess.Popen, prefix: str, color: str) -> None:
    """Read stdout/stderr line-by-line and print with a colored prefix."""
    assert proc.stdout is not None
    try:
        for raw_line in proc.stdout:
            if _shutting_down.is_set():
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            print(f"{color}[{prefix}]{RESET}  {line}", flush=True)
    except (OSError, ValueError):
        pass


def _run_process(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    label: str,
    color: str,
) -> subprocess.Popen | None:
    """Start a subprocess and a reader thread for its output."""
    log(f"{color}Starting {label}...{RESET}")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        log(f"{RED}Failed to start {label}: {exc}{RESET}")
        return None

    with _lock:
        _processes.append(proc)

    reader = threading.Thread(
        target=_stream_output,
        args=(proc, label, color),
        daemon=True,
        name=f"reader-{label}",
    )
    reader.start()
    return proc


def _shutdown_all() -> None:
    """Terminate all managed processes."""
    if _shutting_down.is_set():
        return
    _shutting_down.set()
    log("Shutting down...")
    with _lock:
        procs = list(_processes)
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + 5.0
    for proc in procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
    log("Done.")


def _signal_handler(signum: int, _frame) -> None:
    _shutdown_all()


def run_backend(env: dict[str, str]) -> subprocess.Popen | None:
    return _run_process(
        cmd=["uv", "run", "python", "supervisor.py"],
        cwd=BACKEND_DIR,
        env=env,
        label="backend",
        color=GREEN,
    )


def run_api_backend(env: dict[str, str]) -> subprocess.Popen | None:
    host = env.get("SORTER_API_HOST", "127.0.0.1")
    return _run_process(
        cmd=["uv", "run", "uvicorn", "server.api:app", "--host", host, "--port", "8000"],
        cwd=BACKEND_DIR,
        env=env,
        label="api",
        color=GREEN,
    )


def run_frontend(env: dict[str, str]) -> subprocess.Popen | None:
    return _run_process(
        cmd=["pnpm", "dev"],
        cwd=FRONTEND_DIR,
        env=env,
        label="frontend",
        color=BLUE,
    )


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    env = _load_env()
    log(f"LEGO Sorter — mode: {mode}")

    procs: list[subprocess.Popen] = []

    if mode in ("backend", "all"):
        p = run_backend(env)
        if p:
            procs.append(p)
    elif mode == "api":
        p = run_api_backend(env)
        if p:
            procs.append(p)

    if mode in ("frontend", "all"):
        p = run_frontend(env)
        if p:
            procs.append(p)

    if not procs:
        log(f"{RED}No processes started.{RESET}")
        sys.exit(1)

    # Wait for any process to exit; if one dies, shut everything down.
    try:
        while not _shutting_down.is_set():
            for proc in procs:
                try:
                    proc.wait(timeout=0.5)
                    if not _shutting_down.is_set():
                        log(f"{YELLOW}Process exited (pid={proc.pid}, "
                            f"code={proc.returncode}). Shutting down.{RESET}")
                        _shutdown_all()
                        return
                except subprocess.TimeoutExpired:
                    continue
    except KeyboardInterrupt:
        _shutdown_all()


if __name__ == "__main__":
    main()
