import hashlib
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
manifest_path = project_root / "experiments" / "results" / "swat_a4a5_stage3_2" / "change_manifest.json"

files_to_hash = [
    # Modified sources
    "src/tcmim/gating/structural_mask.py",
    "src/tcmim/gating/gates.py",
    # Modified/New tests
    "tests/unit/test_swat_a4a5_stage3.py",
    "tests/unit/test_swat_a4a5_stage3_2.py",
    # Deliverables
    "experiments/results/swat_a4a5_stage3_2/proposed_connectivity_register_stage3_2.csv",
    "experiments/results/swat_a4a5_stage3_2/corrected_scientific_report.md",
    "experiments/results/swat_a4a5_stage3_2/corrected_model_evaluation.csv",
    "experiments/results/swat_a4a5_stage3_2/corrected_relationship_decisions.csv",
    "experiments/results/swat_a4a5_stage3_2/validation_status_register.csv",
    "experiments/results/swat_a4a5_stage3_2/conditional_gate_design.md",
    "experiments/results/swat_a4a5_stage3_2/test_coverage_update.md",
    "experiments/results/swat_a4a5_stage3_2/test_results.txt",
]

descriptions = {
    "src/tcmim/gating/structural_mask.py": "Implemented StructuralStatus.CONDITIONAL, StateConditionPredicate parser and evaluator, and safe CSV loader.",
    "src/tcmim/gating/gates.py": "Updated gate_structural_mask and GatingPipeline to accept actuator state evidence and fail closed on invalid/missing states.",
    "tests/unit/test_swat_a4a5_stage3.py": "Replaced unsafe unconditional ALLOWED assertion with CONDITIONAL fail-closed assertion.",
    "tests/unit/test_swat_a4a5_stage3_2.py": "17 new scientific regression tests covering conditional gating, audit classifications, and shadow mode safety.",
    "experiments/results/swat_a4a5_stage3_2/proposed_connectivity_register_stage3_2.csv": "Corrected physical connectivity register (EDGE_07 DISALLOWED, EDGE_23 CONDITIONAL on MV201 == 2).",
    "experiments/results/swat_a4a5_stage3_2/corrected_scientific_report.md": "Comprehensive Stage 3.2 scientific report reconciling models, qualifications, and safety decisions.",
    "experiments/results/swat_a4a5_stage3_2/corrected_model_evaluation.csv": "Episode-level and pooled reconciled evaluation metrics with qualified classifications.",
    "experiments/results/swat_a4a5_stage3_2/corrected_relationship_decisions.csv": "Official decision matrix for all 6 investigated candidate relationships.",
    "experiments/results/swat_a4a5_stage3_2/validation_status_register.csv": "Definitive scientific validation status register across all 23 candidate edges.",
    "experiments/results/swat_a4a5_stage3_2/conditional_gate_design.md": "Technical architecture specification for conditional structural edge evaluation in Gate G0.",
    "experiments/results/swat_a4a5_stage3_2/test_coverage_update.md": "Audit of test coverage, replaced assertions, regression suite description, and execution log.",
    "experiments/results/swat_a4a5_stage3_2/test_results.txt": "Execution log of focused tests, regression tests, and full test suite.",
}

entries = []
for rel_path in files_to_hash:
    p = (project_root / rel_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Missing file: {p}")
    b = p.read_bytes()
    sha = hashlib.sha256(b).hexdigest()
    lines = len(b.decode("utf-8", errors="replace").splitlines())
    entries.append({
        "path": rel_path.replace("\\", "/"),
        "sha256": sha,
        "size_bytes": len(b),
        "line_count": lines,
        "description": descriptions.get(rel_path, ""),
    })

manifest = {
    "milestone": "TCMIM Stage 3.2",
    "timestamp_utc": "2026-10-26T16:05:00Z",
    "total_tracked_files": len(entries) + 1,
    "files": entries,
}

manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(f"Successfully generated {manifest_path} with {len(manifest['files'])} entries.")
