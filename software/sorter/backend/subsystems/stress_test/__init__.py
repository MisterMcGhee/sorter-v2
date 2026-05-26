"""C-channel tracking stress test subsystem.

Siloed module that exercises C-channels at varying pulse parameters to find
the limit where the vision tracker loses a piece during transit. Reuses the
same stepper primitives and feeder tracker the main machine runs against, so
results reflect production behavior.
"""
from subsystems.stress_test.algorithm import (
    StressTrialParams,
    StressTrialResult,
    StressTrialStatus,
    buildLinearSweep,
    determineNextStatus,
)
from subsystems.stress_test.c_channel_tracking import (
    CChannelTrackingStressRunner,
    StressTestState,
    StressRunStatus,
    getActiveCChannelTrackingRunner,
    getCChannelTrackingRunner,
)

__all__ = [
    "CChannelTrackingStressRunner",
    "StressTestState",
    "StressRunStatus",
    "StressTrialParams",
    "StressTrialResult",
    "StressTrialStatus",
    "buildLinearSweep",
    "determineNextStatus",
    "getActiveCChannelTrackingRunner",
    "getCChannelTrackingRunner",
]
