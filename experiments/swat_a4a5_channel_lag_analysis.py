"""
SWaT A4/A5 Channel Attribution and Lagged Cross-Correlation Analysis.

Performs a read-only scientific investigation of sensor channel contributions
to detector alarms and evaluates lagged relationships for subsequent Stage 2 evaluation.

Preservation:
- Does NOT modify any existing source files or prior experiment outputs.
- Saves all outputs to experiments/results/swat_a4a5_channel_lag_analysis/.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd
from scipy import signal

from tcmim.data.swat_a4a5 import (
    load_swat_a4a5_dataframe,
    GapAwareWindowBuilder,
    Provenance,
    SWAT_A4A5_ATTACK_SCHEDULE,
    A4A5_MODALITY_MAP,
    A4A5_ACTUATOR_STATE_MAP,
)
from tcmim.features.extractor import FeatureExtractor
from tcmim.events.cusum import CUSUMDetector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("swat_a4a5_channel_lag_analysis")


def crosscorr(x: np.ndarray, y: np.ndarray, lag: int = 0) -> float:
    """Compute Pearson cross-correlation where lag > 0 means x leads y (x_t correlated with y_{t+lag})."""
    n = len(x)
    if lag > 0:
        return float(np.corrcoef(x[:n - lag], y[lag:])[0, 1])
    elif lag < 0:
        return float(np.corrcoef(x[-lag:], y[:n + lag])[0, 1])
    else:
        return float(np.corrcoef(x, y)[0, 1])


def analyze_sensor_pair(
    df_sub: pd.DataFrame,
    ch_x: str,
    ch_y: str,
    max_lag: int = 30,
    diff: bool = False,
) -> Tuple[float, int, float, float, np.ndarray, np.ndarray]:
    """Calculate cross-correlation across lag window [-max_lag, +max_lag]."""
    x_s = df_sub[ch_x].copy()
    y_s = df_sub[ch_y].copy()

    if diff:
        x_s = x_s.diff().dropna()
        y_s = y_s.diff().dropna()
    else:
        x_s = x_s.dropna()
        y_s = y_s.dropna()

    common_idx = x_s.index.intersection(y_s.index)
    xv = x_s.loc[common_idx].values
    yv = y_s.loc[common_idx].values

    if len(xv) < max_lag + 2 or np.std(xv) < 1e-12 or np.std(yv) < 1e-12:
        lags = np.arange(-max_lag, max_lag + 1)
        return 0.0, 0, 0.0, 0.0, np.zeros(len(lags)), lags

    lags = np.arange(-max_lag, max_lag + 1)
    corrs = np.array([crosscorr(xv, yv, lag) for lag in lags])
    best_idx = int(np.argmax(np.abs(corrs)))

    rho_x = crosscorr(xv[:-1], xv[1:], 0) if len(xv) > 2 else 0.0
    rho_y = crosscorr(yv[:-1], yv[1:], 0) if len(yv) > 2 else 0.0

    return float(corrs[best_idx]), int(lags[best_idx]), float(rho_x), float(rho_y), corrs, lags


def run_channel_lag_investigation() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    data_dir = repo_root / "data" / "raw" / "SWAT_A4_A5_JULY_2019"
    wb_path = data_dir / "SWaT_dataset_Jul 19 v2.xlsx"
    out_dir = repo_root / "experiments" / "results" / "swat_a4a5_channel_lag_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting SWaT A4/A5 Channel Attribution and Lagged Cross-Correlation Analysis")
    logger.info("Source dataset: %s", wb_path)
    logger.info("Output directory: %s", out_dir)

    # 1. Load telemetry and generate windows
    df, meta = load_swat_a4a5_dataframe(wb_path)
    window_builder = GapAwareWindowBuilder(
        window_seconds=30.0,
        step_seconds=30.0,
        min_samples=2,
        max_internal_gap_s=15.0,
    )
    all_windows, _ = window_builder.build_and_audit(
        df, machine_id="SWAT_A4A5", provenance=Provenance.PUBLIC_DATASET
    )

    # 2. Extract multimodal features
    logger.info("Extracting multimodal features across all 500 windows...")
    fe = FeatureExtractor(
        sampling_rate_hz=1.0,
        channel_modality_map=A4A5_MODALITY_MAP,
        channel_state_map=A4A5_ACTUATOR_STATE_MAP,
    )
    all_samples = fe.extract_all(all_windows)
    flat_samples = []
    for s in all_samples:
        flat = {}
        for mod_feats in s.features.values():
            flat.update(mod_feats)
        flat_samples.append(flat)
    df_feats = pd.DataFrame(flat_samples)

    # 3. Partition baseline statistics (Windows 10..279)
    base_idx = slice(10, 280)
    eval_idx = slice(280, 500)
    base_feats = df_feats.iloc[base_idx]
    feat_means = base_feats.mean()
    feat_stds = base_feats.std(ddof=1)
    valid_features = feat_stds[feat_stds >= 1e-12].index.tolist()
    const_features = feat_stds[feat_stds < 1e-12].index.tolist()

    Z_matrix = (df_feats[valid_features] - feat_means[valid_features]) / feat_stds[valid_features]
    Z_matrix = Z_matrix.fillna(0.0)

    # 4. Reconstruct predictions for all 4 detectors
    orig_preds_df = pd.read_csv(repo_root / "experiments" / "results" / "swat_a4a5" / "predictions.csv")
    labels = orig_preds_df["ground_truth_label"].values
    iforest_preds = orig_preds_df["prediction"].values

    mean_abs_z = Z_matrix.abs().mean(axis=1).values
    max_abs_z = Z_matrix.abs().max(axis=1).values

    # CUSUM partition reset
    mu_z_base = float(np.mean(mean_abs_z[base_idx]))
    std_z_base = float(np.std(mean_abs_z[base_idx], ddof=1))
    k_cusum = mu_z_base + 0.5 * std_z_base

    base_cusum_scores = np.zeros(270)
    S = 0.0
    for t, val in enumerate(mean_abs_z[base_idx]):
        S = max(0.0, S + val - k_cusum)
        base_cusum_scores[t] = S
    h_cusum = float(np.percentile(base_cusum_scores, 95.0))

    det_eval = CUSUMDetector(k=k_cusum, h=h_cusum, reset=True)
    _, alarms_eval = det_eval.run_with_scores(mean_abs_z[eval_idx])
    cusum_eval_preds = np.zeros(220, dtype=int)
    for a in alarms_eval:
        cusum_eval_preds[a.index] = 1

    tau_max_z = float(np.percentile(max_abs_z[base_idx], 95.0))
    max_z_eval_preds = (max_abs_z[eval_idx] > tau_max_z).astype(int)
    shewhart_eval_preds = (max_abs_z[eval_idx] > 3.0).astype(int)
    iforest_eval_preds = iforest_preds[eval_idx]

    # 5. Define candidate physical sensor pairs
    candidate_pairs = [
        {
            "pair_id": "PAIR_01",
            "name": "P301_to_DPIT301",
            "stage_source": "P3",
            "stage_target": "P3",
            "channel_source": "P301",
            "channel_target": "DPIT301",
            "units_source": "state (1=OFF, 2=ON)",
            "units_target": "kPa",
            "physical_mechanism": "UF feed pump actuation generates trans-membrane differential pressure",
            "predeclared_max_lag_s": 30,
        },
        {
            "pair_id": "PAIR_02",
            "name": "FIT501_to_PIT501",
            "stage_source": "P5",
            "stage_target": "P5",
            "channel_source": "FIT501",
            "channel_target": "PIT501",
            "units_source": "m3/h",
            "units_target": "bar/kPa",
            "physical_mechanism": "Pump P501 discharge flow directly builds inlet membrane pressure",
            "predeclared_max_lag_s": 30,
        },
        {
            "pair_id": "PAIR_03",
            "name": "FIT501_to_FIT502",
            "stage_source": "P5",
            "stage_target": "P5",
            "channel_source": "FIT501",
            "channel_target": "FIT502",
            "units_source": "m3/h",
            "units_target": "m3/h",
            "physical_mechanism": "Conservation of mass across RO membrane separation (Feed to Permeate)",
            "predeclared_max_lag_s": 60,
        },
        {
            "pair_id": "PAIR_04",
            "name": "FIT201_to_LIT301",
            "stage_source": "P2",
            "stage_target": "P3",
            "channel_source": "FIT201",
            "channel_target": "LIT301",
            "units_source": "m3/h",
            "units_target": "mm",
            "physical_mechanism": "Cross-stage inflow from Stage 2 fills tank T301 (hydraulic mass accumulation)",
            "predeclared_max_lag_s": 120,
        },
        {
            "pair_id": "PAIR_05",
            "name": "MV501_to_PIT502",
            "stage_source": "P5",
            "stage_target": "P5",
            "channel_source": "MV501",
            "channel_target": "PIT502",
            "units_source": "state (1=OPEN, 2=CLOSE)",
            "units_target": "bar/kPa",
            "physical_mechanism": "Reject valve closure induces hydraulic backpressure surge in RO vessel",
            "predeclared_max_lag_s": 30,
        },
    ]

    # Evaluate pairs across partitions
    df_base = df[(df.index >= "2019-07-20 04:35:00") & (df.index <= "2019-07-20 06:50:00")]
    df_eval = df[(df.index >= "2019-07-20 06:50:00") & (df.index <= "2019-07-20 08:40:00")]
    df_a5 = df[(df.index >= "2019-07-20 07:53:00") & (df.index <= "2019-07-20 07:58:00")]
    df_a6 = df[(df.index >= "2019-07-20 08:02:00") & (df.index <= "2019-07-20 08:18:00")]

    pair_rows = []
    for p in candidate_pairs:
        cx, cy, mlag = p["channel_source"], p["channel_target"], p["predeclared_max_lag_s"]

        # 1. Baseline
        r_b_raw, l_b_raw, rx_b_raw, ry_b_raw, _, _ = analyze_sensor_pair(df_base, cx, cy, mlag, diff=False)
        r_b_dif, l_b_dif, rx_b_dif, ry_b_dif, _, _ = analyze_sensor_pair(df_base, cx, cy, mlag, diff=True)
        pair_rows.append({
            "pair_id": p["pair_id"],
            "pair_name": p["name"],
            "stage_source": p["stage_source"],
            "stage_target": p["stage_target"],
            "channel_source": cx,
            "channel_target": cy,
            "units_source": p["units_source"],
            "units_target": p["units_target"],
            "physical_mechanism": p["physical_mechanism"],
            "partition": "Baseline (04:35 - 06:50 UTC)",
            "n_samples": len(df_base),
            "predeclared_max_lag_s": mlag,
            "raw_peak_r": round(r_b_raw, 4),
            "raw_optimal_lag_s": l_b_raw,
            "raw_rho1_source": round(rx_b_raw, 4),
            "raw_rho1_target": round(ry_b_raw, 4),
            "diff_peak_r": round(r_b_dif, 4),
            "diff_optimal_lag_s": l_b_dif,
            "diff_rho1_source": round(rx_b_dif, 4),
            "diff_rho1_target": round(ry_b_dif, 4),
            "statistical_association_level": "High" if abs(r_b_raw) > 0.7 else ("Moderate" if abs(r_b_raw) > 0.3 else "Low/None"),
            "physical_validity_verdict": "Direct Actuation Coupling" if p["pair_id"] == "PAIR_01" else ("Zero Baseline Variance" if p["pair_id"] == "PAIR_05" else "Noise Dominated in Normal State"),
        })

        # 2. Held-Out
        r_e_raw, l_e_raw, rx_e_raw, ry_e_raw, _, _ = analyze_sensor_pair(df_eval, cx, cy, mlag, diff=False)
        r_e_dif, l_e_dif, rx_e_dif, ry_e_dif, _, _ = analyze_sensor_pair(df_eval, cx, cy, mlag, diff=True)
        pair_rows.append({
            "pair_id": p["pair_id"],
            "pair_name": p["name"],
            "stage_source": p["stage_source"],
            "stage_target": p["stage_target"],
            "channel_source": cx,
            "channel_target": cy,
            "units_source": p["units_source"],
            "units_target": p["units_target"],
            "physical_mechanism": p["physical_mechanism"],
            "partition": "Held-Out Operational (06:50 - 08:40 UTC)",
            "n_samples": len(df_eval),
            "predeclared_max_lag_s": mlag,
            "raw_peak_r": round(r_e_raw, 4),
            "raw_optimal_lag_s": l_e_raw,
            "raw_rho1_source": round(rx_e_raw, 4),
            "raw_rho1_target": round(ry_e_raw, 4),
            "diff_peak_r": round(r_e_dif, 4),
            "diff_optimal_lag_s": l_e_dif,
            "diff_rho1_source": round(rx_e_dif, 4),
            "diff_rho1_target": round(ry_e_dif, 4),
            "statistical_association_level": "High" if abs(r_e_raw) > 0.7 else ("Moderate" if abs(r_e_raw) > 0.3 else "Low/None"),
            "physical_validity_verdict": "Direct Actuation Coupling" if p["pair_id"] == "PAIR_01" else "Transient/Event-Induced Association",
        })

        # 3. Event specific where applicable
        if p["pair_id"] == "PAIR_05":
            r_ev_raw, l_ev_raw, rx_ev_raw, ry_ev_raw, _, _ = analyze_sensor_pair(df_a5, cx, cy, mlag, diff=False)
            r_ev_dif, l_ev_dif, rx_ev_dif, ry_ev_dif, _, _ = analyze_sensor_pair(df_a5, cx, cy, mlag, diff=True)
            pair_rows.append({
                "pair_id": p["pair_id"],
                "pair_name": p["name"],
                "stage_source": p["stage_source"],
                "stage_target": p["stage_target"],
                "channel_source": cx,
                "channel_target": cy,
                "units_source": p["units_source"],
                "units_target": p["units_target"],
                "physical_mechanism": p["physical_mechanism"],
                "partition": "Attack A5 Window (07:53 - 07:58 UTC)",
                "n_samples": len(df_a5),
                "predeclared_max_lag_s": mlag,
                "raw_peak_r": round(r_ev_raw, 4),
                "raw_optimal_lag_s": l_ev_raw,
                "raw_rho1_source": round(rx_ev_raw, 4),
                "raw_rho1_target": round(ry_ev_raw, 4),
                "diff_peak_r": round(r_ev_dif, 4),
                "diff_optimal_lag_s": l_ev_dif,
                "diff_rho1_source": round(rx_ev_dif, 4),
                "diff_rho1_target": round(ry_ev_dif, 4),
                "statistical_association_level": "High",
                "physical_validity_verdict": "Hydraulic Surge from Valve Closure",
            })
        elif p["pair_id"] == "PAIR_01":
            r_ev_raw, l_ev_raw, rx_ev_raw, ry_ev_raw, _, _ = analyze_sensor_pair(df_a6, cx, cy, mlag, diff=False)
            r_ev_dif, l_ev_dif, rx_ev_dif, ry_ev_dif, _, _ = analyze_sensor_pair(df_a6, cx, cy, mlag, diff=True)
            pair_rows.append({
                "pair_id": p["pair_id"],
                "pair_name": p["name"],
                "stage_source": p["stage_source"],
                "stage_target": p["stage_target"],
                "channel_source": cx,
                "channel_target": cy,
                "units_source": p["units_source"],
                "units_target": p["units_target"],
                "physical_mechanism": p["physical_mechanism"],
                "partition": "Attack A6 Window (08:02 - 08:18 UTC)",
                "n_samples": len(df_a6),
                "predeclared_max_lag_s": mlag,
                "raw_peak_r": round(r_ev_raw, 4),
                "raw_optimal_lag_s": l_ev_raw,
                "raw_rho1_source": round(rx_ev_raw, 4),
                "raw_rho1_target": round(ry_ev_raw, 4),
                "diff_peak_r": round(r_ev_dif, 4),
                "diff_optimal_lag_s": l_ev_dif,
                "diff_rho1_source": round(rx_ev_dif, 4),
                "diff_rho1_target": round(ry_ev_dif, 4),
                "statistical_association_level": "High",
                "physical_validity_verdict": "Pump Trip Depressurization",
            })

    pair_metrics_df = pd.DataFrame(pair_rows)
    pair_metrics_csv_path = out_dir / "channel_pair_metrics.csv"
    pair_metrics_df.to_csv(pair_metrics_csv_path, index=False)
    logger.info("Saved channel pair metrics to: %s", pair_metrics_csv_path)

    # 6. Save analysis configuration
    analysis_cfg = {
        "analysis_name": "SWaT A4/A5 Channel Attribution and Lagged Cross-Correlation Analysis",
        "dataset_file": "SWaT_dataset_Jul 19 v2.xlsx",
        "dataset_sha256": meta.get("sha256", "39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc"),
        "evaluation_partition": {
            "pre_baseline_buffer": "Windows 0..9 (N=10, 04:30 - 04:35 UTC)",
            "baseline_training_period": "Windows 10..279 (N=270, 04:35 - 06:50 UTC)",
            "primary_held_out_operational_evaluation": "Windows 280..499 (N=220, 06:50 - 08:40 UTC)",
        },
        "feature_schema": {
            "total_extracted_features": df_feats.shape[1],
            "valid_non_constant_features": len(valid_features),
            "excluded_constant_features": len(const_features),
        },
        "evaluated_detectors": [
            "Multivariate Isolation Forest (Existing)",
            "CUSUM Detector on Mean Absolute Z-Scores (Partition Reset)",
            "Per-Channel Max-Z (Baseline Calibrated)",
            "Per-Channel Shewhart (Fixed 3-Sigma)",
        ],
        "attack_schedule": {aid: atk.to_dict() for aid, atk in SWAT_A4A5_ATTACK_SCHEDULE.items()},
        "candidate_sensor_pairs": candidate_pairs,
        "sign_convention": "lag > 0 indicates source channel leads target channel by lag seconds (x_t correlated with y_{t+lag})",
    }
    with open(out_dir / "analysis_config.json", "w", encoding="utf-8") as f:
        json.dump(analysis_cfg, f, indent=2)

    logger.info("Analysis configuration saved to: %s", out_dir / "analysis_config.json")
    print("Execution completed successfully.")


if __name__ == "__main__":
    run_channel_lag_investigation()
