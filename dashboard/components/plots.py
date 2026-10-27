"""
dashboard/components/plots.py
==============================
Publication-grade Matplotlib plotting utilities for the TCMIM Two-Node Dashboard.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from dashboard.backend import NodeDetectionResult
from tcmim.schemas import EventRecord


def plot_node_telemetry_and_scores(
    node_res: NodeDetectionResult,
    color: str = "#2563eb",
    title_suffix: str = "",
) -> plt.Figure:
    """Generate a 2-panel chart showing raw telemetry and anomaly detector scores."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 4.5), sharex=True, dpi=120)
    fig.patch.set_facecolor("#ffffff")

    x = node_res.timestamps
    y = node_res.raw_values
    scores = node_res.anomaly_scores
    thresh = node_res.threshold
    anom_mask = np.array(node_res.is_anomaly, dtype=bool)

    # Top panel: Raw Telemetry
    ax1.plot(x, y, color=color, lw=1.5, label=f"{node_res.node_id} Telemetry")
    if np.any(anom_mask):
        ax1.scatter(
            [x[i] for i in range(len(x)) if anom_mask[i]],
            [y[i] for i in range(len(y)) if anom_mask[i]],
            color="#dc2626",
            s=28,
            zorder=5,
            label="Anomalous Window",
        )
    ax1.set_ylabel("Raw Value", fontsize=10, fontweight="bold")
    ax1.set_title(f"{node_res.node_id} — Telemetry Signal {title_suffix}", fontsize=11, fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(loc="upper right", framealpha=0.8, fontsize=8)

    # Bottom panel: Anomaly Score / Detector Statistic
    ax2.plot(x, scores, color="#4b5563", lw=1.3, label=f"{node_res.detector_name} Score")
    ax2.axhline(thresh, color="#dc2626", linestyle=":", lw=1.5, label=f"Threshold ({thresh})")

    if node_res.detector_name == "isolation_forest":
        # Score < threshold is anomaly
        ax2.fill_between(
            x, scores, thresh, where=(np.array(scores) < thresh), color="#fee2e2", alpha=0.6, label="Anomaly Zone"
        )
        ax2.set_ylabel("Decision Score", fontsize=10, fontweight="bold")
    elif node_res.detector_name == "actuator_state_transition":
        ax2.fill_between(
            x, scores, thresh, where=(np.array(scores) < thresh), color="#fee2e2", alpha=0.6, label="Transition Zone"
        )
        ax2.set_ylabel("State Departure", fontsize=10, fontweight="bold")
    else:
        # CUSUM: score > threshold is anomaly
        ax2.fill_between(
            x, scores, thresh, where=(np.array(scores) > thresh), color="#fee2e2", alpha=0.6, label="Alarm Zone"
        )
        ax2.set_ylabel("CUSUM S_t", fontsize=10, fontweight="bold")

    ax2.set_xlabel("Timestamp (UTC)", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(loc="upper right", framealpha=0.8, fontsize=8)

    # Formatting date axis
    if len(x) > 0 and isinstance(x[0], datetime):
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate(rotation=20, ha="right")

    plt.tight_layout()
    return fig


def plot_dual_node_comparison(
    node_a: NodeDetectionResult,
    node_b: NodeDetectionResult,
) -> plt.Figure:
    """Generate a side-by-side comparative plot of Node A vs Node B."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 5.0), sharex=True, dpi=120)
    fig.patch.set_facecolor("#ffffff")

    # Node A Top
    ax1.plot(node_a.timestamps, node_a.raw_values, color="#1e40af", lw=1.6, label=f"Node A: {node_a.node_id}")
    anom_a = np.array(node_a.is_anomaly, dtype=bool)
    if np.any(anom_a):
        ax1.scatter(
            [node_a.timestamps[i] for i in range(len(node_a.timestamps)) if anom_a[i]],
            [node_a.raw_values[i] for i in range(len(node_a.raw_values)) if anom_a[i]],
            color="#ef4444",
            s=30,
            zorder=5,
            label="Node A Anomaly",
        )
    ax1.set_ylabel(f"{node_a.node_id}", fontsize=10, fontweight="bold")
    ax1.set_title(f"Node A ({node_a.node_id}) — Initiating / Source Stream", fontsize=11, fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(loc="upper right", fontsize=8)

    # Node B Bottom
    ax2.plot(node_b.timestamps, node_b.raw_values, color="#047857", lw=1.6, label=f"Node B: {node_b.node_id}")
    anom_b = np.array(node_b.is_anomaly, dtype=bool)
    if np.any(anom_b):
        ax2.scatter(
            [node_b.timestamps[i] for i in range(len(node_b.timestamps)) if anom_b[i]],
            [node_b.raw_values[i] for i in range(len(node_b.raw_values)) if anom_b[i]],
            color="#f97316",
            s=30,
            zorder=5,
            label="Node B Anomaly",
        )
    ax2.set_ylabel(f"{node_b.node_id}", fontsize=10, fontweight="bold")
    ax2.set_title(f"Node B ({node_b.node_id}) — Potential Response Stream", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Timestamp (UTC)", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(loc="upper right", fontsize=8)

    if len(node_a.timestamps) > 0 and isinstance(node_a.timestamps[0], datetime):
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate(rotation=20, ha="right")

    plt.tight_layout()
    return fig


def plot_event_timeline(
    evt_a: Optional[EventRecord],
    evt_b: Optional[EventRecord],
    delta_t_s: Optional[float],
) -> plt.Figure:
    """Render a clean timeline diagram displaying event onset alignment."""
    fig, ax = plt.subplots(figsize=(10, 2.4), dpi=120)
    fig.patch.set_facecolor("#ffffff")

    ax.set_ylim(-0.8, 1.2)
    ax.axhline(0, color="#9ca3af", lw=2, zorder=1)

    if evt_a is None and evt_b is None:
        ax.text(0.5, 0.2, "No Events Detected Onset", ha="center", va="center", fontsize=11, color="#6b7280")
        ax.axis("off")
        return fig

    # Reference timeline in seconds from evt_a
    t0 = evt_a.onset_time if evt_a else (evt_b.onset_time if evt_b else datetime.now(timezone.utc))

    if evt_a:
        t_a_rel = 0.0
        ax.scatter([t_a_rel], [0], color="#2563eb", s=180, zorder=5, label=f"Node A ({evt_a.machine_id})")
        ax.annotate(
            f"Node A Onset\n{evt_a.onset_time.strftime('%H:%M:%S')}",
            (t_a_rel, 0.15),
            ha="center",
            fontsize=9,
            fontweight="bold",
            color="#1e40af",
        )

    if evt_b:
        t_b_rel = (evt_b.onset_time - t0).total_seconds() if evt_a else 0.0
        ax.scatter([t_b_rel], [0], color="#059669", s=180, zorder=5, label=f"Node B ({evt_b.machine_id})")
        ax.annotate(
            f"Node B Onset\n{evt_b.onset_time.strftime('%H:%M:%S')}",
            (t_b_rel, 0.15),
            ha="center",
            fontsize=9,
            fontweight="bold",
            color="#065f46",
        )

        if evt_a and delta_t_s is not None:
            # Draw delta_t bracket
            mid_x = t_b_rel / 2.0
            ax.plot([0, t_b_rel], [-0.35, -0.35], color="#dc2626", lw=2.0, linestyle="--")
            ax.plot([0, 0], [-0.25, -0.45], color="#dc2626", lw=2.0)
            ax.plot([t_b_rel, t_b_rel], [-0.25, -0.45], color="#dc2626", lw=2.0)
            ax.annotate(
                f"Δt = {delta_t_s:.2f} s",
                (mid_x, -0.6),
                ha="center",
                fontsize=10,
                fontweight="bold",
                color="#b91c1c",
            )

    ax.set_yticks([])
    ax.set_xlabel("Relative Time Offset (seconds)", fontsize=9)
    ax.grid(True, axis="x", linestyle=":", alpha=0.6)
    ax.legend(loc="upper right", framealpha=0.9, fontsize=8)

    plt.tight_layout()
    return fig
