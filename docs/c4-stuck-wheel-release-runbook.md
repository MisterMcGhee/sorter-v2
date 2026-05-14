# C4 Stuck Wheel Release Runbook

Use this when a wheel or rubber part sticks on the C4 platter near the exit.
This is real hardware: do not skip gates.

## Current Safety Gates

1. Motor power is off or the physical emergency stop is engaged.
2. Flash the feeder Pico with firmware that reports `stepper_cancel: true`.
3. Restart the backend/supervisor so the Python halt and supervisor-stop fixes are live.
4. Confirm the live backend reports `hardware_state: ready`.
5. Confirm `/api/hardware-config/control-boards/live` shows the feeder board with `supports_stepper_cancel: true`.
6. Confirm C4 reports `stepper_stopped: true`.
7. Keep a human at the machine with physical power cut-off ready.

## Firmware Build And Flash

Builds already pass locally, but flash only with one Pico in BOOTSEL mode at a time.

Before flashing, verify the built images are the updated ones:

```sh
cd software/sorter/backend
PYTHONPATH=. uv run python scripts/c4_stuck_wheel_release.py --verify-firmware-artifacts
```

The manual equivalent is:

```sh
cd software/firmware/sorter_interface_firmware
shasum -a 256 build-feeder/sorter_interface_firmware.uf2 build-distribution/sorter_interface_firmware.uf2
strings build-feeder/sorter_interface_firmware.uf2 | rg "stepper_cancel|CANCEL|FEEDER|c_channel_1_rotor|carousel"
strings build-distribution/sorter_interface_firmware.uf2 | rg "stepper_cancel|CANCEL|DISTRIBUTION|chute_stepper"
```

Expected: both images contain `stepper_cancel` and `CANCEL`; feeder contains
`FEEDER` / `c_channel_1_rotor` / `carousel`; distribution contains
`DISTRIBUTION` / `chute_stepper`.

```sh
cd software/firmware/sorter_interface_firmware
make flash-feeder
```

C4 is on the feeder-role board. Flash distribution separately only if needed:

```sh
cd software/firmware/sorter_interface_firmware
make flash-distribution
```

## Dry Run

This does not touch the backend or hardware.

```sh
cd software/sorter/backend
PYTHONPATH=. uv run python scripts/c4_stuck_wheel_release.py --stage 1
```

## Passive Preflight

This calls only read/passive endpoints. It does not pause, move, home, or stop
hardware.

```sh
cd software/sorter/backend
PYTHONPATH=. uv run python scripts/c4_stuck_wheel_release.py --preflight
```

If the backend is supervised, also require the fixed supervisor marker:

```sh
cd software/sorter/backend
PYTHONPATH=. uv run python scripts/c4_stuck_wheel_release.py --preflight --require-supervisor-safe
```

Stage 1 is intentionally tiny:

- `+0.25 deg` output
- `-0.5 deg` output
- `+0.25 deg` output
- repeated twice

## First Live Stage

Run only after all gates above are true.

```sh
cd software/sorter/backend
PYTHONPATH=. uv run python scripts/c4_stuck_wheel_release.py \
  --execute \
  --stage 1 \
  --confirm-each-stroke \
  --prompt-after-stroke \
  --capture-frames \
  --stroke-stop-timeout 3.0 \
  --confirm-live-c4 STUCK-WHEEL \
  --confirm-firmware-cancel CANCEL-FLASHED
```

The script pauses the sorter, verifies live feeder firmware capability, checks
C4 is stopped, verifies the supervisor reports `manual_stop_safe: true` by
default, executes only the selected stage, captures optional carousel frames into
`/tmp/c4_stuck_wheel_release/run_<id>/frames`, then sends `/stepper/stop` and
keeps the sorter paused. It writes both `timeline.json` and `summary.json` into
the run directory, including failed runs where a stroke timeout/error occurred.

Only if the backend is deliberately running standalone without the supervisor,
add `--skip-supervisor-check STANDALONE-BACKEND`.

With `--prompt-after-stroke`, answer `r` if the wheel released or `a` if the
stroke looked/sounded wrong. Either answer stops the remaining strokes and still
runs the final stop/pause cleanup.

`--stroke-stop-timeout` is intentionally short because Stage 1 strokes are only
12/24/12 microsteps. If C4 does not report stopped inside that window, the probe
sends `/stepper/stop` and aborts.

## Compare Runs

After one or more gated live attempts, summarize which run and stroke released
the wheel:

```sh
cd software/sorter/backend
PYTHONPATH=. uv run python scripts/c4_stuck_wheel_release.py --report
```

This is offline analysis only; it reads `run_*/summary.json` under
`/tmp/c4_stuck_wheel_release`.

## Escalation

Do not use `--all-stages` for the first test. Advance one stage at a time only
after visually confirming the previous stage was calm and did not produce
irregular stepper speed.

## Abort Conditions

Immediately cut motor power and stop the run if any of these happen:

- pitch rises into fast/irregular stepper speed
- C4 moves more than the planned small rock
- backend reports a stop/cancel failure
- `/api/hardware-config/carousel/live` does not return `stepper_stopped: true`
  after a stroke
