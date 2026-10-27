"""
TCMIM — Physical Structural Connectivity Mask (M-PHY, G0).

Provides a non-invasive physical connectivity constraint for Stage 2
candidate-edge processing. Operates as Gate G0 before delay feasibility (G1).

Mathematical definition:
------------------------
Let V be the set of physical plant components (sensors, actuators).
M_phys in {0, 1, ?}^(N x N)
- 1 (ALLOWED)   : Documented or physically inferred piping, wiring, or interlock.
- 0 (DISALLOWED): Physically impossible, structurally blocked, or isolated.
- ? (UNKNOWN)   : Missing or insufficiently documented.

Scientific integrity rule:
--------------------------
A missing register entry is NOT evidence of physical impossibility.
Missing entries default to UNKNOWN ('?').
"""

from __future__ import annotations

import csv
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class StructuralStatus(str, Enum):
    """Status of a physical connectivity prior edge.

    '1': Unconditionally permitted by physical prior.
    '0': Explicitly prohibited by physical architecture.
    'C': Conditional on specific operating / actuator states.
    '?': Unknown or insufficiently documented.
    """
    ALLOWED = "1"
    DISALLOWED = "0"
    CONDITIONAL = "C"
    UNKNOWN = "?"

    @classmethod
    def from_raw(cls, val: Any) -> "StructuralStatus":
        """Convert a raw string, integer, or enum value to StructuralStatus."""
        if isinstance(val, cls):
            return val
        s = str(val).strip().upper()
        if s in ("1", "ALLOWED", "PERMITTED", "DOCUMENTED"):
            return cls.ALLOWED
        if s in ("0", "DISALLOWED", "PROHIBITED", "NO_DISALLOWED"):
            return cls.DISALLOWED
        if s in ("C", "CONDITIONAL"):
            return cls.CONDITIONAL
        if s in ("?", "UNKNOWN", "UNVERIFIED"):
            return cls.UNKNOWN
        if s in ("INFERRED",):
            # Preserved for backward compatibility with older string schemas where INFERRED meant permitted.
            # When loaded via PhysicalStructuralMask.load_from_csv, suitable_as_structural_constraint
            # is independently inspected to ensure conditional edges are not improperly promoted.
            return cls.ALLOWED
        raise ValueError(
            f"Invalid structural status '{val}'. "
            f"Must be one of '1' (ALLOWED/DOCUMENTED), '0' (DISALLOWED/PROHIBITED), "
            f"'C' (CONDITIONAL), or '?' (UNKNOWN/UNVERIFIED)."
        )

    @property
    def is_allowed(self) -> bool:
        return self == StructuralStatus.ALLOWED

    @property
    def is_disallowed(self) -> bool:
        return self == StructuralStatus.DISALLOWED

    @property
    def is_conditional(self) -> bool:
        return self == StructuralStatus.CONDITIONAL

    @property
    def is_unknown(self) -> bool:
        return self == StructuralStatus.UNKNOWN


@dataclass(frozen=True)
class StateConditionPredicate:
    """Explicit operating-state predicate for a conditional structural edge.

    Example: MV201 == 2
    """
    actuator: str
    operator: str
    required_value: Any
    raw_expression: str

    @classmethod
    def parse(cls, expr: str) -> "StateConditionPredicate":
        """Parse expression such as 'MV201 == 2' or 'MV201 == 2 (OPEN)'."""
        expr_clean = expr.strip()
        if not expr_clean:
            raise ValueError("Predicate expression cannot be empty.")

        for op in ("==", "!=", ">=", "<=", ">", "<", " in "):
            clean_op = op.strip()
            if clean_op in expr_clean:
                parts = expr_clean.split(clean_op, 1)
                actuator = parts[0].strip()
                val_raw = parts[1].strip()
                # Strip comments or parenthetical descriptions like (OPEN)
                if "(" in val_raw:
                    val_raw = val_raw.split("(", 1)[0].strip()

                if not actuator or not val_raw:
                    raise ValueError(f"Malformed predicate expression: '{expr}'")

                # Parse value
                val: Any
                try:
                    val = int(val_raw)
                except ValueError:
                    try:
                        val = float(val_raw)
                    except ValueError:
                        val = val_raw.strip("'\"")

                return cls(
                    actuator=actuator,
                    operator=clean_op,
                    required_value=val,
                    raw_expression=expr_clean,
                )
        raise ValueError(f"No supported operator found in predicate expression: '{expr}'")

    def evaluate(
        self,
        evidence: Optional[Dict[str, Any]],
        *,
        max_age_s: Optional[float] = None,
        current_time: Optional[Any] = None,
        require_freshness: bool = False,
    ) -> Tuple[bool, str]:
        """Evaluate predicate against actuator state evidence.

        Fails closed on missing, invalid, unknown, stale, or contradictory evidence.
        """
        if evidence is None or not isinstance(evidence, dict):
            return False, "missing actuator state evidence (evidence is None or not a dict)"

        if self.actuator not in evidence:
            return False, f"actuator '{self.actuator}' missing from state evidence"

        entry = evidence[self.actuator]

        # Extract value, timestamp, quality, staleness flag
        raw_val: Any
        timestamp: Optional[Any] = None
        quality: str = "GOOD"
        is_stale: bool = False

        if isinstance(entry, dict):
            raw_val = entry.get("value")
            timestamp = entry.get("timestamp")
            quality = str(entry.get("quality", "GOOD")).strip().upper()
            is_stale = bool(entry.get("is_stale", False))
            if quality in ("BAD", "INVALID", "UNCERTAIN", "CONTRADICTORY"):
                return False, f"actuator '{self.actuator}' state quality invalid: {quality}"
            if is_stale:
                return False, f"actuator '{self.actuator}' state is flagged as stale"
        else:
            raw_val = entry

        if raw_val is None:
            return False, f"actuator '{self.actuator}' state value is None"

        # Check for unknown / invalid sentinel strings
        if isinstance(raw_val, str):
            clean_s = raw_val.strip().upper()
            if clean_s in ("?", "UNKNOWN", "NAN", "INVALID", "CONTRADICTORY", "STALE", "MISSING", "NONE"):
                return False, f"actuator '{self.actuator}' state is invalid/unknown: '{raw_val}'"

        # Check freshness if configured or requested
        if require_freshness and timestamp is None:
            return False, f"actuator '{self.actuator}' state lacks timestamp required for freshness verification"

        if max_age_s is not None:
            if timestamp is None:
                if require_freshness:
                    return False, f"actuator '{self.actuator}' state lacks timestamp required for freshness verification"
            elif current_time is not None:
                try:
                    t_cur = current_time.timestamp() if hasattr(current_time, "timestamp") else float(current_time)
                    t_rec = timestamp.timestamp() if hasattr(timestamp, "timestamp") else float(timestamp)
                    age = t_cur - t_rec
                    if age < 0 or age > max_age_s:
                        return False, f"actuator '{self.actuator}' state is stale: age {age:.1f}s exceeds max_age_s={max_age_s}s"
                except (ValueError, TypeError) as e:
                    return False, f"actuator '{self.actuator}' timestamp comparison failed: {e}"

        # Type alignment for numeric comparison
        cmp_val = raw_val
        if isinstance(self.required_value, (int, float)) and not isinstance(raw_val, (int, float)):
            try:
                cmp_val = float(raw_val)
                if isinstance(self.required_value, int) and cmp_val.is_integer():
                    cmp_val = int(cmp_val)
            except (ValueError, TypeError):
                return False, f"cannot convert actuator '{self.actuator}' value '{raw_val}' to numeric"

        # Operator evaluation
        try:
            if self.operator == "==":
                satisfied = (cmp_val == self.required_value)
            elif self.operator == "!=":
                satisfied = (cmp_val != self.required_value)
            elif self.operator == ">=":
                satisfied = (cmp_val >= self.required_value)
            elif self.operator == "<=":
                satisfied = (cmp_val <= self.required_value)
            elif self.operator == ">":
                satisfied = (cmp_val > self.required_value)
            elif self.operator == "<":
                satisfied = (cmp_val < self.required_value)
            elif self.operator == "in":
                satisfied = (cmp_val in self.required_value)
            else:
                return False, f"unsupported operator '{self.operator}'"
        except Exception as e:
            return False, f"comparison error evaluating '{self.raw_expression}': {e}"

        if satisfied:
            return True, f"actuator condition satisfied: {self.actuator} ({cmp_val}) {self.operator} {self.required_value}"
        else:
            return False, f"actuator condition failed: {self.actuator} ({cmp_val}) {self.operator} {self.required_value} is false"


@dataclass
class PhysicalConnectivityRecord:
    """Auditable record of a single directed edge in the physical connectivity register.

    Keeps documentary status, physical-mask status, baseline identifiability,
    dynamic-validation status, and operating-state predicate as separate fields.
    """
    edge_id: str
    source_component: str
    destination_component: str
    source_stage: str
    destination_stage: str
    relationship_type: str
    documented_direction: str
    documentary_status: str                     # DOCUMENTED, INFERRED, UNKNOWN, DISALLOWED, CONDITIONAL
    mask_status: StructuralStatus               # ALLOWED ('1'), DISALLOWED ('0'), CONDITIONAL ('C'), UNKNOWN ('?')
    supporting_document: str
    document_page_or_id: str
    evidence_confidence: str                    # HIGH, MEDIUM, LOW
    suitable_as_structural_constraint: str      # YES, NO, CONDITIONAL, NO_DISALLOWED
    dynamically_validated: bool                 # False until verified by dynamic perturbation
    baseline_identifiability: str               # IDENTIFIABLE, UNIDENTIFIABLE_*, SPURIOUS_*
    physical_mechanism_and_notes: str = ""
    operating_condition: str = ""
    condition_predicate: Optional[StateConditionPredicate] = None

    def __post_init__(self) -> None:
        if not self.source_component or not self.source_component.strip():
            raise ValueError(f"Invalid record '{self.edge_id}': source_component cannot be empty.")
        if not self.destination_component or not self.destination_component.strip():
            raise ValueError(f"Invalid record '{self.edge_id}': destination_component cannot be empty.")
        if not isinstance(self.mask_status, StructuralStatus):
            self.mask_status = StructuralStatus.from_raw(self.mask_status)
        if self.operating_condition and not self.condition_predicate:
            try:
                self.condition_predicate = StateConditionPredicate.parse(self.operating_condition)
            except Exception as e:
                logger.warning(
                    "Failed to parse operating_condition '%s' on %s: %s",
                    self.operating_condition, self.edge_id, e,
                )


# Default set of unexcited actuators from SWaT A4/A5 baseline variance audit (sigma == 0.0)
DEFAULT_UNEXCITED_ACTUATORS: Set[str] = {
    "P601", "MV501", "P102", "P201", "P202", "P204", "P206",
    "MV301", "MV303", "P302", "P401", "P402", "UV401", "P501",
    "P502", "P602", "P603",
}


def get_default_register_path() -> Path:
    """Resolve default physical connectivity register path relative to project root.

    Does not depend on the current working directory.
    """
    # structural_mask.py is located at <project_root>/src/tcmim/gating/structural_mask.py
    project_root = Path(__file__).resolve().parents[3]
    candidate = (
        project_root
        / "experiments"
        / "results"
        / "swat_a4a5_physical_graph_audit"
        / "physical_connectivity_register.csv"
    )
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"Default physical connectivity register not found at project location: {candidate}"
    )


@dataclass
class StructuralMaskConfig:
    """Configuration for physical structural mask evaluation.

    Attributes
    ----------
    register_path           : Optional path to CSV register. If None, resolved via project root.
    allow_unknown           : Policy for edges with mask_status == '?'.
                              False: conservative SWaT mode (rejects unverified edges).
                              True: compatibility mode (allows unverified edges to proceed).
    unexcited_actuators     : Set of component IDs with zero baseline variance.
    structural_prior_weight : Configurable prior weight W_prior for unexcited edges (default 0.5).
    """
    register_path: Optional[Path] = None
    allow_unknown: bool = False
    unexcited_actuators: Set[str] = field(default_factory=lambda: set(DEFAULT_UNEXCITED_ACTUATORS))
    structural_prior_weight: float = 0.5


class PhysicalStructuralMask:
    """In-memory physical structural mask matrix and query interface.

    Loads and validates the physical connectivity register, guaranteeing:
    - Path resolution relative to project root (no reliance on os.getcwd()).
    - Strict validation against duplicates, conflicting definitions, and invalid statuses.
    - Safe default: missing edges return UNKNOWN ('?'), never DISALLOWED ('0').
    - Clear distinction between documentary status, mask status, baseline identifiability,
      and dynamic validation status.
    """

    def __init__(
        self,
        records: Optional[Dict[Tuple[str, str], PhysicalConnectivityRecord]] = None,
        config: Optional[StructuralMaskConfig] = None,
        register_sha256: str = "",
        register_path: Optional[Path] = None,
    ) -> None:
        self.config = config or StructuralMaskConfig()
        self._records: Dict[Tuple[str, str], PhysicalConnectivityRecord] = records or {}
        self.register_sha256 = register_sha256
        self.register_path = register_path
        self.unexcited_actuators = set(self.config.unexcited_actuators)

    @classmethod
    def load_from_csv(
        cls,
        csv_path: Optional[Path | str] = None,
        config: Optional[StructuralMaskConfig] = None,
    ) -> "PhysicalStructuralMask":
        """Load and validate register from CSV file.

        Parameters
        ----------
        csv_path : Path to CSV. If None, uses config.register_path or project default.
        config   : Optional StructuralMaskConfig.

        Returns
        -------
        Instantiated and validated PhysicalStructuralMask.

        Raises
        ------
        FileNotFoundError : If the CSV file does not exist.
        ValueError        : If the CSV contains duplicate edges, conflicting definitions,
                            empty identifiers, or invalid mask statuses.
        """
        cfg = config or StructuralMaskConfig()
        resolved_path: Path
        if csv_path is not None:
            resolved_path = Path(csv_path).resolve()
        elif cfg.register_path is not None:
            resolved_path = Path(cfg.register_path).resolve()
        else:
            resolved_path = get_default_register_path()

        if not resolved_path.is_file():
            raise FileNotFoundError(
                f"Physical connectivity register not found: {resolved_path}"
            )

        content_bytes = resolved_path.read_bytes()
        sha256_hash = hashlib.sha256(content_bytes).hexdigest()

        records: Dict[Tuple[str, str], PhysicalConnectivityRecord] = {}

        # Parse CSV with DictReader
        text = content_bytes.decode("utf-8-sig")
        reader = csv.DictReader(text.splitlines())

        required_columns = {"source_component", "destination_component", "status"}
        if not required_columns.issubset(set(reader.fieldnames or [])):
            missing = required_columns - set(reader.fieldnames or [])
            raise ValueError(
                f"Physical connectivity register missing required column(s): {missing}. "
                f"Found: {reader.fieldnames}"
            )

        for line_num, row in enumerate(reader, start=2):
            raw_src = row.get("source_component", "")
            raw_dst = row.get("destination_component", "")

            src = raw_src.strip()
            dst = raw_dst.strip()

            if not src:
                raise ValueError(
                    f"Malformed register entry at line {line_num}: "
                    f"source_component is empty."
                )
            if not dst:
                raise ValueError(
                    f"Malformed register entry at line {line_num}: "
                    f"destination_component is empty."
                )

            edge_key = (src, dst)
            raw_status = row.get("status", "").strip()
            suitable_raw = row.get("suitable_as_structural_constraint", "").strip().upper()
            op_cond = row.get("operating_condition", "").strip()
            notes = row.get("physical_mechanism_and_notes", "").strip()

            # Extract condition if not in dedicated column but present in notes
            if not op_cond and "conditional on " in notes.lower():
                tail = notes[notes.lower().index("conditional on ") + len("conditional on "):]
                for sep in [";", ".", "\n"]:
                    tail = tail.split(sep)[0]
                op_cond = tail.strip()

            # Conditionality resolution:
            # 1. If explicitly DISALLOWED, it remains DISALLOWED.
            # 2. If status is CONDITIONAL / C, or operating_condition is provided/extracted, it is CONDITIONAL.
            if raw_status.upper() in ("0", "DISALLOWED", "PROHIBITED", "NO_DISALLOWED") or suitable_raw == "NO_DISALLOWED":
                mask_status = StructuralStatus.DISALLOWED
            elif raw_status.upper() in ("C", "CONDITIONAL") or bool(op_cond):
                mask_status = StructuralStatus.CONDITIONAL
            else:
                try:
                    mask_status = StructuralStatus.from_raw(raw_status)
                except ValueError as e:
                    raise ValueError(
                        f"Invalid mask status at line {line_num} for edge '{src}' -> '{dst}': {e}"
                    ) from e

            # Check for duplicates or conflicting definitions
            if edge_key in records:
                existing = records[edge_key]
                if existing.mask_status != mask_status:
                    raise ValueError(
                        f"Conflicting duplicate edge definition at line {line_num} for '{src}' -> '{dst}': "
                        f"previously defined with status {existing.mask_status.value} ({existing.documentary_status}), "
                        f"re-defined with status {mask_status.value} ({raw_status})."
                    )
                else:
                    raise ValueError(
                        f"Duplicate edge definition at line {line_num} for '{src}' -> '{dst}' "
                        f"(edge_id: '{row.get('edge_id', '')}')."
                    )

            # Parse boolean for dynamic validation
            raw_dyn = row.get("dynamically_validated", "False").strip().lower()
            dyn_val = raw_dyn in ("true", "1", "yes")

            pred: Optional[StateConditionPredicate] = None
            if op_cond:
                try:
                    pred = StateConditionPredicate.parse(op_cond)
                except Exception as e:
                    logger.warning(
                        "Line %d: Failed to parse operating condition '%s' on %s: %s",
                        line_num, op_cond, row.get("edge_id", ""), e,
                    )

            record = PhysicalConnectivityRecord(
                edge_id=row.get("edge_id", f"EDGE_{len(records)+1:02d}").strip(),
                source_component=src,
                destination_component=dst,
                source_stage=row.get("source_stage", "").strip(),
                destination_stage=row.get("destination_stage", "").strip(),
                relationship_type=row.get("relationship_type", "").strip(),
                documented_direction=row.get("documented_direction", "FORWARD").strip(),
                documentary_status=raw_status,
                mask_status=mask_status,
                supporting_document=row.get("supporting_document", "").strip(),
                document_page_or_id=row.get("document_page_or_id", "").strip(),
                evidence_confidence=row.get("evidence_confidence", "MEDIUM").strip(),
                suitable_as_structural_constraint=row.get("suitable_as_structural_constraint", "YES").strip(),
                dynamically_validated=dyn_val,
                baseline_identifiability=row.get("baseline_identifiability", "IDENTIFIABLE").strip(),
                physical_mechanism_and_notes=notes,
                operating_condition=op_cond,
                condition_predicate=pred,
            )
            records[edge_key] = record

        logger.info(
            "Loaded physical connectivity register: %d edges from %s (SHA-256: %s)",
            len(records), resolved_path.name, sha256_hash[:12],
        )

        return cls(
            records=records,
            config=cfg,
            register_sha256=sha256_hash,
            register_path=resolved_path,
        )

    def get_status(self, source: str, destination: str) -> StructuralStatus:
        """Query the structural mask status for a directed candidate edge.

        Returns
        -------
        StructuralStatus:
            ALLOWED ('1')    : If documented or physically inferred.
            DISALLOWED ('0') : If explicitly prohibited.
            CONDITIONAL ('C'): If conditional on specific operating states.
            UNKNOWN ('?')    : If missing from register or marked unknown.
                               (Missing entries NEVER default to DISALLOWED).
        """
        key = (source.strip(), destination.strip())
        rec = self._records.get(key)
        if rec is not None:
            return rec.mask_status
        # Missing register entries are UNKNOWN, not DISALLOWED
        return StructuralStatus.UNKNOWN

    def get_record(self, source: str, destination: str) -> Optional[PhysicalConnectivityRecord]:
        """Retrieve full auditable connectivity record for a pair, or None if unregistered."""
        key = (source.strip(), destination.strip())
        return self._records.get(key)

    def is_permitted(
        self,
        source: str,
        destination: str,
        state_evidence: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Return True if the edge is permitted under the physical prior.

        - Unconditional ALLOWED ('1'): returns True.
        - CONDITIONAL ('C'): returns True if and only if state_evidence is provided
          and the operating-state predicate is satisfied. Fails closed (False) on missing,
          unknown, or invalid evidence.
        - DISALLOWED ('0') / UNKNOWN ('?'): returns False.
        """
        status = self.get_status(source, destination)
        if status == StructuralStatus.ALLOWED:
            return True
        if status == StructuralStatus.CONDITIONAL:
            rec = self.get_record(source, destination)
            if rec is None or rec.condition_predicate is None:
                return False
            if state_evidence is None:
                return False
            satisfied, _ = rec.condition_predicate.evaluate(state_evidence)
            return satisfied
        return False

    def is_prohibited(self, source: str, destination: str) -> bool:
        """Return True if the edge is explicitly prohibited (status == '0')."""
        return self.get_status(source, destination) == StructuralStatus.DISALLOWED

    def is_conditional(self, source: str, destination: str) -> bool:
        """Return True if the edge is registered as CONDITIONAL ('C')."""
        return self.get_status(source, destination) == StructuralStatus.CONDITIONAL

    def is_unknown(self, source: str, destination: str) -> bool:
        """Return True if the edge is unknown or unregistered (status == '?')."""
        return self.get_status(source, destination) == StructuralStatus.UNKNOWN

    def is_unexcited(self, component: str) -> bool:
        """Return True if the component is registered as an unexcited actuator."""
        return component.strip() in self.unexcited_actuators

    def all_records(self) -> List[PhysicalConnectivityRecord]:
        """Return list of all registered physical connectivity records."""
        return list(self._records.values())

    def permitted_edges(self) -> List[Tuple[str, str]]:
        """Return list of all (source, destination) pairs permitted unconditionally by mask ('1')."""
        return [k for k, r in self._records.items() if r.mask_status == StructuralStatus.ALLOWED]

    def conditional_edges(self) -> List[Tuple[str, str]]:
        """Return list of all (source, destination) pairs registered as CONDITIONAL ('C')."""
        return [k for k, r in self._records.items() if r.mask_status == StructuralStatus.CONDITIONAL]

    def prohibited_edges(self) -> List[Tuple[str, str]]:
        """Return list of all (source, destination) pairs prohibited by mask ('0')."""
        return [k for k, r in self._records.items() if r.mask_status == StructuralStatus.DISALLOWED]

    def unknown_edges(self) -> List[Tuple[str, str]]:
        """Return list of all (source, destination) pairs registered as unknown ('?')."""
        return [k for k, r in self._records.items() if r.mask_status == StructuralStatus.UNKNOWN]

    def add_edge(
        self,
        source: str,
        destination: str,
        status: Any,
        edge_id: Optional[str] = None,
        documentary_status: Optional[str] = None,
        baseline_identifiability: str = "IDENTIFIABLE",
        dynamically_validated: bool = False,
        operating_condition: str = "",
        condition_predicate: Optional[StateConditionPredicate] = None,
    ) -> None:
        """Add or update an edge in memory (primarily for unit testing and fixtures)."""
        src = source.strip()
        dst = destination.strip()
        if not src or not dst:
            raise ValueError("source and destination must be non-empty.")
        mask_status = StructuralStatus.from_raw(status)
        doc_status = documentary_status or (
            "DOCUMENTED" if mask_status.is_allowed
            else "DISALLOWED" if mask_status.is_disallowed
            else "CONDITIONAL" if mask_status.is_conditional
            else "UNKNOWN"
        )
        eid = edge_id or f"CUSTOM_{len(self._records)+1:02d}"
        pred = condition_predicate
        if operating_condition and pred is None:
            pred = StateConditionPredicate.parse(operating_condition)

        rec = PhysicalConnectivityRecord(
            edge_id=eid,
            source_component=src,
            destination_component=dst,
            source_stage="",
            destination_stage="",
            relationship_type="",
            documented_direction="FORWARD",
            documentary_status=doc_status,
            mask_status=mask_status,
            supporting_document="In-memory test fixture",
            document_page_or_id="",
            evidence_confidence="HIGH",
            suitable_as_structural_constraint=(
                "YES" if mask_status.is_allowed
                else "CONDITIONAL" if mask_status.is_conditional
                else "NO_DISALLOWED" if mask_status.is_disallowed
                else "UNKNOWN"
            ),
            dynamically_validated=dynamically_validated,
            baseline_identifiability=baseline_identifiability,
            physical_mechanism_and_notes="",
            operating_condition=operating_condition,
            condition_predicate=pred,
        )
        self._records[(src, dst)] = rec
