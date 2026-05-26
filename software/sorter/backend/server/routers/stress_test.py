"""Router for the C-channel tracking stress test."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import shared_state
from subsystems.stress_test import (
    CChannelTrackingStressRunner,
    getActiveCChannelTrackingRunner,
    getCChannelTrackingRunner,
)
from subsystems.stress_test.algorithm import StressSweepConfig


router = APIRouter()


class StartStressTestRequest(BaseModel):
    top_speed: int = Field(..., gt=0)
    min_speed: int = Field(..., gt=0)
    speed_step: int = Field(..., gt=0)
    pulse_steps: int = Field(..., gt=0)
    start_pause_ms: int = Field(0, ge=0)
    max_pause_ms: int = Field(0, ge=0)
    pause_step_ms: int = Field(0, ge=0)
    acceleration_microsteps_per_second_sq: int = Field(20000, gt=0)
    track_loss_grace_observations: int = Field(2, ge=0)


class StressTestStateResponse(BaseModel):
    active: bool
    run: Optional[dict[str, Any]] = None


def _hardwareWorkerAlive() -> bool:
    worker = shared_state.hardware_worker_thread
    return bool(worker is not None and worker.is_alive())


def _ensureManualMotionAllowed() -> None:
    state = shared_state.hardware_state
    if _hardwareWorkerAlive() or state in {"homing", "initializing"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot run C-channel stress test while hardware is {state}.",
        )


def _resolveHardware() -> dict[str, Any]:
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(
            status_code=503,
            detail="Hardware not initialized. Start or home the system first.",
        )
    c1 = getattr(irl, "c_channel_1_rotor_stepper", None)
    c2 = getattr(irl, "c_channel_2_rotor_stepper", None)
    if c1 is None or c2 is None:
        raise HTTPException(status_code=500, detail="C-channel steppers unavailable")
    vision = shared_state.vision_manager
    if vision is None:
        raise HTTPException(status_code=503, detail="Vision manager not initialized")
    gc = getattr(c1, "_gc", None) or shared_state.gc_ref
    return {"gc": gc, "c1": c1, "c2": c2, "vision": vision, "irl": irl}


def _resolveFeederConfig() -> Any:
    # IRLConfig (carrying feeder_config) is held by the controller's
    # coordinator, not by IRLInterface itself. Walk the controller_ref →
    # coordinator → irl_config chain to find it.
    controller = shared_state.controller_ref
    irl_config = None
    if controller is not None:
        coordinator = getattr(controller, "coordinator", None)
        if coordinator is not None:
            irl_config = getattr(coordinator, "irl_config", None)
    if irl_config is None:
        # Fall back to a couple of names the IRLInterface may itself carry
        # in some test/setup paths.
        irl = shared_state.getActiveIRL()
        if irl is not None:
            irl_config = getattr(irl, "irl_config", None) or getattr(
                irl, "_irl_config", None
            )
    feeder_cfg = getattr(irl_config, "feeder_config", None) if irl_config else None
    if feeder_cfg is None:
        raise HTTPException(status_code=500, detail="feeder_config unavailable")
    return feeder_cfg


def _activeRunner() -> CChannelTrackingStressRunner:
    runner = getActiveCChannelTrackingRunner()
    if runner is None:
        raise HTTPException(status_code=409, detail="No stress test is running.")
    return runner


@router.post("/api/c-channel-tracking-stress-test/start", response_model=StressTestStateResponse)
def startStressTest(payload: StartStressTestRequest) -> StressTestStateResponse:
    _ensureManualMotionAllowed()
    hw = _resolveHardware()
    gc = hw["gc"]
    if gc is None:
        raise HTTPException(status_code=500, detail="GlobalConfig unavailable on stepper")
    feeder = _resolveFeederConfig()
    c1_cfg = feeder.first_rotor
    c2_cfg = feeder.second_rotor_normal

    runner = getCChannelTrackingRunner(
        gc,
        c1_stepper=hw["c1"],
        c2_stepper=hw["c2"],
        vision=hw["vision"],
        c1_pulse_steps=int(c1_cfg.steps_per_pulse),
        c1_speed_microsteps_per_second=int(c1_cfg.microsteps_per_second),
        c1_acceleration_microsteps_per_second_sq=int(
            c1_cfg.acceleration_microsteps_per_second_sq or 20000
        ),
        c1_delay_between_pulse_ms=int(c1_cfg.delay_between_pulse_ms),
        c2_default_speed_microsteps_per_second=int(c2_cfg.microsteps_per_second),
        c2_default_acceleration_microsteps_per_second_sq=int(
            c2_cfg.acceleration_microsteps_per_second_sq or 20000
        ),
    )

    try:
        sweep = StressSweepConfig(
            top_speed=int(payload.top_speed),
            min_speed=int(payload.min_speed),
            speed_step=int(payload.speed_step),
            pulse_steps=int(payload.pulse_steps),
            start_pause_ms=int(payload.start_pause_ms),
            max_pause_ms=int(payload.max_pause_ms),
            pause_step_ms=int(payload.pause_step_ms),
            acceleration_microsteps_per_second_sq=int(
                payload.acceleration_microsteps_per_second_sq
            ),
            track_loss_grace_observations=int(payload.track_loss_grace_observations),
        )
        state = runner.start(sweep)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return StressTestStateResponse(active=True, run=state.toDict())


@router.post("/api/c-channel-tracking-stress-test/pause", response_model=StressTestStateResponse)
def pauseStressTest() -> StressTestStateResponse:
    runner = _activeRunner()
    try:
        runner.pause()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )


@router.post("/api/c-channel-tracking-stress-test/resume", response_model=StressTestStateResponse)
def resumeStressTest() -> StressTestStateResponse:
    runner = _activeRunner()
    try:
        runner.resume()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )


@router.post("/api/c-channel-tracking-stress-test/stop", response_model=StressTestStateResponse)
def stopStressTest() -> StressTestStateResponse:
    runner = _activeRunner()
    try:
        runner.stop()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )


@router.get("/api/c-channel-tracking-stress-test/status", response_model=StressTestStateResponse)
def getStressTestStatus() -> StressTestStateResponse:
    runner = getActiveCChannelTrackingRunner()
    if runner is None:
        return StressTestStateResponse(active=False, run=None)
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )
