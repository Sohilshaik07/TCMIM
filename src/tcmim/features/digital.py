"""
TCMIM — Digital state feature extraction (S2, FR-FE-5).

Digital channels represent discrete actuator states or binary operational flags:
- Standard binary signals: 0 = Inactive / Off, 1 = Active / On (e.g., MetroPT-3).
- Positive categorical signals: e.g., SWaT pumps/valves where 1 = Closed/Off, 2 = Open/On.

Features computed
-----------------
  mode_state    : Most common binary state (1.0 = active, 0.0 = inactive) based on
                  the mapped active state. NaN if no valid mapped states exist.
  duty_cycle    : Fraction of valid mapped samples where the actuator is active (1).
                  NaN if no valid mapped states exist in the window.
  n_transitions : Number of actual changes between consecutive states in the raw signal.
                  Counts physical state transitions directly (not thresholded > 0).
  first_state   : Raw unnormalized state at the start of the window.
  last_state    : Raw unnormalized state at the end of the window.

State Mapping and Unknown State Policy
--------------------------------------
- Default mapping (state_mapping=None): assumes standard binary encoding {0.0: 0, 1.0: 1}.
- Tag-aware mapping: caller supplies a mapping such as {1.0: 0, 2.0: 1} where 1 is
  inactive (0) and 2 is active (1).
- Unknown / Intermediate States: Any raw state not present in the mapping (e.g., state 0
  for valves in transition or fault) is treated explicitly as UNKNOWN. It is NEVER
  silently classified as ON (1) or OFF (0).
  - Transitions to/from unknown states are counted in `n_transitions`.
  - Unknown states are excluded from the binary active/inactive ratio in `duty_cycle`.
  - If an entire window contains only unknown states, `duty_cycle` and `mode_state` evaluate to NaN.
- Raw Signal Preservation: The input signal is never mutated in-place. `first_state`
  and `last_state` always report the exact raw observed values.

Requirements coverage: FR-FE-5 (P1)
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Union

import numpy as np

logger = logging.getLogger(__name__)


def compute_digital_features(
    signal: np.ndarray,
    *,
    state_mapping: Optional[Dict[Union[int, float], int]] = None,
) -> Dict[str, float]:
    """Compute digital state features from a discrete actuator signal.

    Parameters
    ----------
    signal        : 1-D array of discrete numerical state values. Preserved unmodified.
    state_mapping : Optional mapping from raw state value to binary active flag
                    (1 = Active/ON, 0 = Inactive/OFF).
                    If None, defaults to standard binary interpretation {0.0: 0, 1.0: 1}.

    Returns
    -------
    Dict mapping feature name → float.
    """
    if len(signal) < 1:
        return {k: float("nan") for k in (
            "mode_state", "duty_cycle", "n_transitions",
            "first_state", "last_state"
        )}

    # Ensure 1-D array without mutating original input
    arr = np.asarray(signal, dtype=float)

    first_state = float(arr[0])
    last_state = float(arr[-1])

    # 1. Transitions: Count actual state changes between consecutive raw samples
    if len(arr) < 2:
        n_transitions = 0.0
    else:
        diffs = np.abs(np.diff(arr))
        n_transitions = float(np.sum(diffs > 1e-9))

    # 2. State Mapping and Normalization
    mapping = state_mapping if state_mapping is not None else {0.0: 0, 1.0: 1}
    norm_mapping = {float(k): int(v) for k, v in mapping.items()}

    valid_mapped_states = []
    for val in arr:
        matched_val = None
        for k_state, v_binary in norm_mapping.items():
            if np.isclose(val, k_state, atol=1e-6):
                matched_val = v_binary
                break
        if matched_val is not None:
            valid_mapped_states.append(matched_val)

    n_valid = len(valid_mapped_states)
    if n_valid == 0:
        # Policy: If no valid mapped states exist in the window, duty_cycle and mode_state are NaN
        duty_cycle = float("nan")
        mode_state = float("nan")
    else:
        active_count = sum(1 for s in valid_mapped_states if s == 1)
        duty_cycle = float(active_count / n_valid)
        mode_state = float(np.round(duty_cycle))

    return {
        "mode_state":    mode_state,
        "duty_cycle":    duty_cycle,
        "n_transitions": n_transitions,
        "first_state":   first_state,
        "last_state":    last_state,
    }

