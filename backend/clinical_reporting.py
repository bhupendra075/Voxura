"""Validated structured-finding contract and deterministic report rendering.

This module deliberately contains no free-form generative model. A future GPU worker
must produce this contract before any text can enter a clinician draft.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EvidenceReference(BaseModel):
    series_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)
    frame: int = Field(ge=0)
    coordinates: list[float] = Field(default_factory=list, max_length=12)


class Measurement(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    value: float
    unit: Literal["mm", "mm2", "mm3", "mL", "count", "percent"]


class StructuredFinding(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=240)
    assertion: Literal["present", "absent", "uncertain"]
    anatomy: str = Field(min_length=1, max_length=160)
    laterality: Literal["left", "right", "bilateral", "midline", "not_applicable", "unknown"]
    urgency: Literal["critical", "urgent", "routine", "incidental"]
    status: Literal["proposed", "accepted", "edited", "rejected", "invalidated"] = "proposed"
    probability: float | None = Field(None, ge=0, le=1)
    uncertainty: str = Field(default="", max_length=500)
    model_id: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    evidence: list[EvidenceReference] = Field(min_length=1)
    measurements: list[Measurement] = Field(default_factory=list)
    impression_clause: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def accepted_finding_has_known_location(self):
        if self.status in {"accepted", "edited"} and self.laterality == "unknown":
            raise ValueError("accepted findings require resolved laterality")
        return self


class StructuredAnalysisResult(BaseModel):
    schema_version: Literal[1] = 1
    findings: list[StructuredFinding]
    warnings: list[str] = Field(default_factory=list)
    complete: bool = False


def compose_review_draft(result: StructuredAnalysisResult) -> tuple[str, str]:
    """Render only clinician-accepted facts; never turn missing output into normality."""
    accepted = [finding for finding in result.findings if finding.status in {"accepted", "edited"}]
    urgency_order = {"critical": 0, "urgent": 1, "routine": 2, "incidental": 3}
    accepted.sort(key=lambda finding: (urgency_order[finding.urgency], finding.anatomy, finding.label))
    finding_lines: list[str] = []
    impression_lines: list[str] = []
    for finding in accepted:
        side = "" if finding.laterality == "not_applicable" else f"{finding.laterality} "
        measures = ", ".join(f"{item.name} {item.value:g} {item.unit}" for item in finding.measurements)
        suffix = f" ({measures})" if measures else ""
        finding_lines.append(f"- {finding.assertion.capitalize()}: {side}{finding.anatomy} — {finding.label}{suffix}.")
        if finding.impression_clause:
            impression_lines.append(f"- {finding.impression_clause.strip().rstrip('.')}.")
    if not accepted:
        warning = "No clinician-accepted model findings are available; this is not a normal-study conclusion."
        return warning, "Radiologist interpretation required."
    if not result.complete:
        finding_lines.append("- Analysis coverage was incomplete; review all source sequences independently.")
    return "\n".join(finding_lines), "\n".join(impression_lines) or "Radiologist impression required."
