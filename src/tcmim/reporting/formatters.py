"""
TCMIM — Report formatters (M8).

Converts structured JSON reports from ReportBuilder into formatted strings
(JSON, Markdown).
"""

from __future__ import annotations

import json
from typing import Any, Dict


class ReportFormatter:
    """Format structured reports into various string representations."""

    @staticmethod
    def to_json(report: Dict[str, Any], indent: int = 2) -> str:
        """Convert report to formatted JSON string."""
        return json.dumps(report, indent=indent)

    @staticmethod
    def to_markdown(report: Dict[str, Any]) -> str:
        """Convert report to Markdown format."""
        lines = []
        lines.append("# TCMIM Pipeline Report")
        lines.append(f"**Generated:** {report['timestamp']}")
        lines.append(f"**Graph Version:** {report['graph_version']}")
        lines.append(f"**Overall Provenance:** `{report['overall_provenance']}`")
        lines.append("")

        if report.get("warnings"):
            for w in report["warnings"]:
                lines.append(f"> ⚠️ **{w}**")
            lines.append("")
            
        lines.append(f"> *{report['disclaimer']}*")
        lines.append("")

        # CRI section
        lines.append("## Cascade Risk Index (CRI)")
        if not report["cri_records"]:
            lines.append("*No CRI records available.*")
        else:
            lines.append("| Target Machine | CRI | Top Contributor |")
            lines.append("|---|---|---|")
            for cr in report["cri_records"]:
                top_contributor = "None"
                if cr["contributions"]:
                    # Get key with max value
                    top_contributor = max(cr["contributions"].items(), key=lambda x: x[1])[0]
                lines.append(f"| {cr['target_machine']} | {cr['cri']:.3f} | {top_contributor} |")
        lines.append("")

        # Edges section
        lines.append("## Active Propagation Edges")
        if not report["edges"]:
            lines.append("*No active edges.*")
        else:
            lines.append("| Source → Target | State | Evidence | Confidence | Provenance |")
            lines.append("|---|---|---|---|---|")
            for e in report["edges"]:
                lines.append(
                    f"| {e['source']} → {e['target']} | {e['state']} | "
                    f"{e['evidence_count']} | {e['confidence']:.3f} | "
                    f"`{e['provenance']}` |"
                )
        lines.append("")
        
        return "\n".join(lines)
