"""
dashboard/app.py
================
TCMIM Two-Node Research Dashboard (Streamlit Application).

Demonstrates:
- Node A (initiating/source) independent anomaly detection.
- Node B (potentially affected/responding) independent anomaly detection.
- Cross-node temporal association, physical gating (G0), operating-state resolution,
  delay feasibility (G1), and common-cause diagnostics (OC-CCD).
- Preserves scientific boundaries and fails closed on unvalidated regimes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import streamlit as st

from dashboard.backend import (
    MANDATORY_DISCLAIMER,
    CrossNodeAnalysisResult,
    NodeDetectionResult,
    NodeTelemetry,
    PresentationStatus,
    evaluate_cross_node_relationship,
    export_experiment_record,
    export_observations_csv,
    load_swat_node_telemetry,
    load_synthetic_benchmark_telemetry,
    load_user_csv_telemetry,
    run_node_detection,
)
from dashboard.components.plots import (
    plot_dual_node_comparison,
    plot_event_timeline,
    plot_node_telemetry_and_scores,
)

# Set page configuration
st.set_page_config(
    page_title="TCMIM — Two-Node Research Dashboard",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for research aesthetics
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1e3a8a;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #4b5563;
        margin-bottom: 1.0rem;
    }
    .disclaimer-banner {
        background-color: #fffbeb;
        border-left: 5px solid #f59e0b;
        padding: 0.75rem 1.0rem;
        border-radius: 4px;
        margin-bottom: 1.25rem;
        color: #92400e;
        font-size: 0.9rem;
    }
    .kpi-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.85rem;
        text-align: center;
    }
    .kpi-title {
        font-size: 0.8rem;
        color: #64748b;
        font-weight: 600;
        text-transform: uppercase;
        margin-bottom: 0.25rem;
    }
    .kpi-value {
        font-size: 1.3rem;
        font-weight: 700;
        color: #0f172a;
    }
    .badge-pass {
        color: #166534;
        background-color: #dcfce7;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    .badge-reject {
        color: #991b1b;
        background-color: #fee2e2;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    .badge-quarantine {
        color: #6b21a8;
        background-color: #f3e8ff;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Header Section
# ---------------------------------------------------------------------------

st.markdown('<div class="main-title">🔬 TCMIM — Two-Node Detection & Response Analysis</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Temporal Cross-Machine Influence Modeling: Software-Based Experimental Verification Dashboard</div>',
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="disclaimer-banner">
        <strong>⚠️ Scientific Boundary Notice:</strong> {MANDATORY_DISCLAIMER}
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar Configuration
# ---------------------------------------------------------------------------

st.sidebar.header("⚙️ Experiment Configuration")

# Input Mode Selection
input_mode = st.sidebar.selectbox(
    "Select Input Mode:",
    [
        "Mode 1: Real SWaT Physical Nodes (Verified Testbed)",
        "Mode 2: Controlled Synthetic Benchmark",
        "Mode 3: User CSV Upload",
    ],
    index=0,
)

node_a_telemetry: Optional[NodeTelemetry] = None
node_b_telemetry: Optional[NodeTelemetry] = None
operating_evidence: Dict[str, Any] = {}
is_user_data: bool = False
override_bounds: Optional[Tuple[float, float]] = None

if "Mode 1" in input_mode:
    swat_preset = st.sidebar.selectbox(
        "SWaT Physical Pair Preset:",
        [
            "MV201 -> FIT201 (Inlet Valve -> Stage 2 Flow: Hydrodynamic Coupling)",
            "P301 -> DPIT301 (UF Feed Pump -> Differential Pressure: State-Dependent)",
            "P101 -> FIT101 (Negative Control: Blocked by Gate G0)",
        ],
        index=0,
    )
    max_rows = st.sidebar.slider("Telemetry Window Size (rows):", min_value=300, max_value=3000, value=1200, step=100)

    if "MV201 -> FIT201" in swat_preset:
        node_a_id = "MV201"
        node_b_id = "FIT201"
    elif "P301 -> DPIT301" in swat_preset:
        node_a_id = "P301"
        node_b_id = "DPIT301"
        st.sidebar.markdown("---")
        st.sidebar.subheader("Actuator Telemetry (MV302)")
        mv302_choice = st.sidebar.radio(
            "Operating Regime for MV302:",
            [
                "State S2: Normal Startup (MV302 == 1, CLOSED) [Validated Bounds [5, 55]s]",
                "State S3: Attack A6 Permeate Open (MV302 == 2, OPEN) [QUARANTINED]",
                "Unknown / Missing Telemetry (Fail-Closed)",
            ],
            index=0,
        )
        if "State S2" in mv302_choice:
            operating_evidence = {"MV302": 1}
        elif "State S3" in mv302_choice:
            operating_evidence = {"MV302": 2}
        else:
            operating_evidence = {"MV302": None}
    else:
        node_a_id = "P101"
        node_b_id = "FIT101"

    try:
        with st.spinner("Loading SWaT testbed telemetry..."):
            node_a_telemetry = load_swat_node_telemetry(node_a_id, max_rows=max_rows)
            node_b_telemetry = load_swat_node_telemetry(node_b_id, max_rows=max_rows)
    except Exception as e:
        st.sidebar.error(f"Error loading SWaT telemetry: {e}")

elif "Mode 2" in input_mode:
    synthetic_scenario = st.sidebar.selectbox(
        "Benchmark Scenario:",
        [
            "scenario_1_chain (Node A -> Node B with 15s delay)",
            "scenario_4_negative_control (Uncoupled Independent Noise)",
            "scenario_5_reversed (Reversed Temporal Order: Target precedes Source)",
        ],
        index=0,
    )
    scen_id = synthetic_scenario.split(" ")[0]
    node_a_telemetry = load_synthetic_benchmark_telemetry(scen_id, "Node_A")
    node_b_telemetry = load_synthetic_benchmark_telemetry(scen_id, "Node_B")
    override_bounds = (10.0, 20.0)

else:
    is_user_data = True
    st.sidebar.info("Upload CSV files for Node A and Node B. Unvalidated relationships will report UNKNOWN.")
    csv_file_a = st.sidebar.file_uploader("Upload Node A CSV:", type=["csv"], key="csv_a")
    csv_file_b = st.sidebar.file_uploader("Upload Node B CSV:", type=["csv"], key="csv_b")

    if csv_file_a and csv_file_b:
        try:
            node_a_telemetry = load_user_csv_telemetry(csv_file_a.getvalue(), "User_Node_A")
            node_b_telemetry = load_user_csv_telemetry(csv_file_b.getvalue(), "User_Node_B")
        except Exception as e:
            st.sidebar.error(f"CSV Validation Error: {e}")

st.sidebar.markdown("---")
st.sidebar.subheader("🔎 Detector Parameters")

detector_choice = st.sidebar.selectbox(
    "Anomaly Detector:",
    ["Isolation Forest (Multimodal / Unsupervised)", "CUSUM (Sequential Degradation)"],
    index=0,
)

if "Isolation Forest" in detector_choice:
    det_type = "isolation_forest"
    contamination = st.sidebar.slider("Contamination (Outlier fraction):", 0.01, 0.15, 0.05, 0.01)
    threshold = st.sidebar.number_input("Anomaly Score Threshold (score < thresh is anomalous):", value=0.0, step=0.02)
    cusum_k, cusum_h = 0.5, 5.0
else:
    det_type = "cusum"
    cusum_k = st.sidebar.slider("CUSUM Reference Slack (k):", 0.1, 2.0, 0.5, 0.1)
    cusum_h = st.sidebar.slider("CUSUM Decision Threshold (h):", 1.0, 15.0, 5.0, 0.5)
    contamination, threshold = 0.05, 0.0

window_size = st.sidebar.slider("Window Size (samples):", 10, 60, 30, 5)
step_size = st.sidebar.slider("Step Stride (samples):", 2, 20, 10, 2)


# ---------------------------------------------------------------------------
# Pipeline Execution
# ---------------------------------------------------------------------------

if node_a_telemetry is None or node_b_telemetry is None:
    st.warning("Please configure or upload valid telemetry for both Node A and Node B.")
    st.stop()

# Run independent detection on Node A and Node B
try:
    res_a = run_node_detection(
        node_a_telemetry,
        detector_type=det_type,
        contamination=contamination,
        threshold=threshold,
        cusum_k=cusum_k,
        cusum_h=cusum_h,
        window_size=window_size,
        step_size=step_size,
    )
    res_b = run_node_detection(
        node_b_telemetry,
        detector_type=det_type,
        contamination=contamination,
        threshold=threshold,
        cusum_k=cusum_k,
        cusum_h=cusum_h,
        window_size=window_size,
        step_size=step_size,
    )
except Exception as e:
    st.error(f"Error during node detection: {e}")
    st.stop()

# Run cross-node gating and evaluation
analysis = evaluate_cross_node_relationship(
    res_a,
    res_b,
    operating_evidence=operating_evidence,
    is_user_data=is_user_data,
    override_delay_bounds=override_bounds,
)


# ---------------------------------------------------------------------------
# Section 1: Top KPI Summary Cards
# ---------------------------------------------------------------------------

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown('<div class="kpi-card">', unsafe_allow_html=True)
    st.markdown(f'<div class="kpi-title">Node A ({res_a.node_id})</div>', unsafe_allow_html=True)
    if res_a.anomalous_count > 0:
        st.markdown(f'<span class="badge-reject">ANOMALOUS ({res_a.anomalous_count} pts)</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge-pass">NOMINAL</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="kpi-card">', unsafe_allow_html=True)
    st.markdown(f'<div class="kpi-title">Node B ({res_b.node_id})</div>', unsafe_allow_html=True)
    if res_b.anomalous_count > 0:
        st.markdown(f'<span class="badge-reject">ANOMALOUS ({res_b.anomalous_count} pts)</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge-pass">NOMINAL</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col3:
    st.markdown('<div class="kpi-card">', unsafe_allow_html=True)
    st.markdown('<div class="kpi-title">Estimated Lag (Δt)</div>', unsafe_allow_html=True)
    dt_str = f"{analysis.delta_t_s:.2f} s" if analysis.delta_t_s is not None else "N/A"
    st.markdown(f'<div class="kpi-value">{dt_str}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col4:
    st.markdown('<div class="kpi-card">', unsafe_allow_html=True)
    st.markdown('<div class="kpi-title">Gate G0 Physical Mask</div>', unsafe_allow_html=True)
    g0_step = next((g for g in analysis.gate_steps if g.gate_name == "GATE_G0_STRUCTURAL_MASK"), None)
    if g0_step and g0_step.passed:
        st.markdown('<span class="badge-pass">ALLOWED</span>', unsafe_allow_html=True)
    elif g0_step and g0_step.status == "UNKNOWN":
        st.markdown('<span class="badge-quarantine">UNKNOWN / UNVALIDATED</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge-reject">DISALLOWED</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with col5:
    st.markdown('<div class="kpi-card">', unsafe_allow_html=True)
    st.markdown('<div class="kpi-title">Overall Verdict</div>', unsafe_allow_html=True)
    verdict = analysis.overall_status.value
    if verdict == "RELATIONSHIP_SUPPORTED":
        st.markdown(f'<span class="badge-pass">{verdict}</span>', unsafe_allow_html=True)
    elif verdict in ("RESPONSE_OBSERVED", "TEMPORAL_ASSOCIATION_OBSERVED"):
        st.markdown(f'<span class="badge-pass" style="background:#e0f2fe; color:#0369a1;">{verdict}</span>', unsafe_allow_html=True)
    elif verdict == "UNKNOWN":
        st.markdown(f'<span class="badge-quarantine">{verdict}</span>', unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="badge-reject">{verdict}</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section 2: Interactive Event Timeline & Explanation
# ---------------------------------------------------------------------------

st.subheader("⏱️ Temporal Alignment & Event Onsets")
st.pyplot(plot_event_timeline(analysis.source_event, analysis.target_event, analysis.delta_t_s))

st.info(f"**Research Assessment:** {analysis.explanation}")


# ---------------------------------------------------------------------------
# Section 3: Telemetry Signals and Detection Scoring
# ---------------------------------------------------------------------------

st.subheader("📊 Independent Telemetry Streams & Anomaly Scores")

tab_comp, tab_node_a, tab_node_b = st.tabs(["Dual Node Comparison", f"Node A: {res_a.node_id}", f"Node B: {res_b.node_id}"])

with tab_comp:
    st.pyplot(plot_dual_node_comparison(res_a, res_b))

with tab_node_a:
    st.markdown(f"**Detector:** `{res_a.detector_name}` | **Anomalous Windows:** {res_a.anomalous_count} | **First Onset:** {res_a.first_onset_time}")
    st.pyplot(plot_node_telemetry_and_scores(res_a, color="#1e40af", title_suffix="(Source Node)"))

with tab_node_b:
    st.markdown(f"**Detector:** `{res_b.detector_name}` | **Anomalous Windows:** {res_b.anomalous_count} | **First Onset:** {res_b.first_onset_time}")
    st.pyplot(plot_node_telemetry_and_scores(res_b, color="#047857", title_suffix="(Target Node)"))


# ---------------------------------------------------------------------------
# Section 4: Gate Execution Trace & Explanations
# ---------------------------------------------------------------------------

st.subheader("🛡️ Gate Execution Audit Trace")

trace_rows = []
for g in analysis.gate_steps:
    icon = "✅" if g.passed else ("⚠️" if g.status in ("QUARANTINED", "UNKNOWN") else "❌")
    trace_rows.append({
        "Gate": g.gate_name,
        "Result": f"{icon} {g.status}",
        "Reason": g.reason,
    })

st.table(pd.DataFrame(trace_rows))


# ---------------------------------------------------------------------------
# Section 5: Experiment Export & Reproducibility
# ---------------------------------------------------------------------------

st.subheader("💾 Experiment Export & Reproducibility")

config_meta = {
    "input_mode": input_mode,
    "source_node": res_a.node_id,
    "target_node": res_b.node_id,
    "detector_type": det_type,
    "contamination": contamination,
    "threshold": threshold,
    "cusum_k": cusum_k,
    "cusum_h": cusum_h,
    "window_size": window_size,
    "step_size": step_size,
    "operating_evidence": operating_evidence,
}

json_export_str = export_experiment_record(analysis, res_a, res_b, config_meta)
csv_export_str = export_observations_csv(res_a, res_b)

col_exp1, col_exp2 = st.columns(2)

with col_exp1:
    st.download_button(
        label="📥 Download Experiment Record (JSON)",
        data=json_export_str,
        file_name=f"tcmim_experiment_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
    )

with col_exp2:
    st.download_button(
        label="📥 Download Observations & Scores (CSV)",
        data=csv_export_str,
        file_name=f"tcmim_observations_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

st.caption("All exports record complete parameter snapshots, gate outcomes, and integrity disclaimers for peer-review.")
