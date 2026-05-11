this is the software for our lego sorting machine called "Sorter"

# status

We're still in the middle of bringing up the Orange Pi system. Things that worked fine on the Mac may hit new, environment-specific issues on the Pi (services, paths, permissions, hardware access, etc.). Expect rough edges there and don't assume parity with the Mac dev setup.

# conventions

## python
- camelCase functions: `searchSets`, `fetchSetInventory`
- under_score local variables and parameters: `api_key`, `set_num`
- UPPER_SNAKE_CASE module-level constants: `REBRICKABLE_API_BASE`
- no docstrings, no comments (except for non-obvious WHY)
- proper type annotations throughout
- `GlobalConfig` is passed as first argument (`gc`) to almost all functions — it carries the logger and all runtime config. exceptions: simple pure functions with no side effects and no logging needs
- never add `#!/usr/bin/env python3` shebangs to new files; if one already exists in a file, leave it alone

# logs
running `./software/dev.sh --dump` writes a per-run log to `software/logs/<YYYY-MM-DD_HH-MM-SS>.log` (one file per invocation). check the most recent file there to see what happened on the last run.

# running commands

- **Never run a long-lived process (server, dev runner, watcher) in the foreground via Bash with a long timeout.** It blocks the conversation while the user sits there. Anything that doesn't return quickly on its own — vite, uvicorn, dev.sh, pnpm dev, tailing logs, polling loops — must run via `run_in_background`, a systemd unit on the target host, or `nohup ... &` over ssh with the ssh call itself returning fast. Don't follow such a launch with `sleep N && tail` in the same call; do the launch in one fast call, then read logs in a separate call only if needed.
- Reserve long Bash timeouts for commands that *should* take a long time but will exit on their own (large installs, heavy syncs). They are not a tool for "wait around in case the thing eventually finishes."

# hardware

The sorter is a Lego piece sorting machine with the following hardware:

- **Feeder system** — several stepper-controlled stages that move pieces through the machine
- **Center chute** — a large chute that directs pieces to the output
- **Circular bin tower** — a rotating tower of bins; the chute distributes pieces into the correct bin by rotating it
- **5 stepper motors total** across the feeder and bin tower

No vibration motors or conveyors anywhere in the machine.

## Firmware boards (RPi Picos)

Two Pico boards, each flashed with the same firmware but different `HW_*` and `FIRMWARE_ROLE` compile flags. Defined in `software/firmware/sorter_interface_firmware/`:

- **Basically (FEEDER MB)** (`hwcfg_basically.h`) — default build target; controls the feeder rotors (`first/second/third_c_channel_rotor`) and the `carousel`
- **SKR Pico** (`hwcfg_skr_pico.h`) — built with `-DHW_SKR_PICO=ON`; controls the `chute_stepper` and the `carousel` (plus distribution aux channels)

Each board exposes 4 stepper channels. `FIRMWARE_ROLE` is either `"feeder"` or `"distribution"` and remaps channel-to-motor names accordingly.

# software architecture

Three components:

- **Backend** (also called "python") — FastAPI/Python service, primary machine controller. ~90% of work happens here.
- **Frontend** — SvelteKit UI.
- **Firmware** — C++, runs on the microcontroller. Minimal logic; mostly executes commands sent by the backend.

# development environment

Two machines, distinct roles. The flow:

1. **You are on the Mac.** Repo lives at `/Users/spencer/Documents/GitHub/sorter-v2-03/`. Shell, git, edits — all Mac.
2. **Code edits happen here on the Mac.** This is the source-of-truth checkout and where commits are made. The Pi's checkout is a deployment target, not a development copy.
3. **After every code edit, `scp` the file(s) to the Pi** at the matching relative path under `/home/orangepi/sorter-v2/`. Do not batch — sync immediately. Use `root-pi` (Tailscale-SSH alias for root) since `orangepi` requires sudo passwords:
   ```bash
   scp <local-path> root-pi:/home/orangepi/sorter-v2/<same-relative-path>
   ssh root-pi 'chown orangepi:orangepi /home/orangepi/sorter-v2/<same-relative-path>'
   ```
   Then restart the affected service if it caches the file: `ssh root-pi 'systemctl restart sorter-backend-dev'` (vite has HMR; most frontend edits don't need a restart).
4. **Pi-only files (`software/machine.toml`, `software/.env`, `software/mine/*.json`) are edited directly on the Pi.** They are gitignored and machine-specific. Do not round-trip them through the Mac repo.
5. **Pi infra/OS changes** (anything under `/etc/`, systemd units, package installs, USB/kernel tweaks, SSH config, tailscale) — document them in `orange_pi/` within the `sorter-v2-agent-notes` repo. The Pi's `/etc/` is not in the repo, so an undocumented change is invisible to future agents.

**Git policy:** commit only when something is verified working, stage only files you actually touched (other agents may be working in parallel), and **never `git push` unless the user explicitly asks.**

- **Mac** — edit files here. Nothing runs or is tested here.
- **Orange Pi** — the actual sorting machine. All builds, services, and hardware tests run here. **Always use `ssh root-pi`** (Tailscale-SSH alias for root). Never use `ssh pi` or `ssh orangepi@...`. See `sorter-v2-agent-notes/orange_pi/` for full SSH, service, and infra details.

# multi-agent

Multiple agents may be running simultaneously in this project. This is unlikely to cause bugs but can cause confusion — if something seems inconsistent, consider that another agent may have made recent changes.

# agent notes

Agent notes live in a separate repo: `sorter-v2-agent-notes` (sibling to this repo on disk at `/Users/spencer/Documents/GitHub/sorter-v2-agent-notes/`). These are internal agent-facing docs — learnings about the env, hardware quirks, infra changes, etc. that help future sessions avoid relearning.

- **Read** them at the start of every session.
- **Write** new notes or updates there when you discover something worth preserving.
- **Commit** changes directly to that repo (it has its own git). Do not commit AGENT_NOTES/ in this repo — it stays gitignored here.
- **Pi infra/OS changes** (anything under `/etc/`, systemd units, package installs, USB/kernel tweaks, SSH config, tailscale) — document them in `orange_pi/` within the agent notes repo. The Pi's `/etc/` is not in the main repo, so an undocumented change is invisible to future agents.
