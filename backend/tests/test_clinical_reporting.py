import pytest
from pydantic import ValidationError

from clinical_reporting import EvidenceReference, StructuredAnalysisResult, StructuredFinding, compose_review_draft


def finding(**changes):
    values = {
        "id": "finding-1", "code": "example", "label": "restricted diffusion", "assertion": "present",
        "anatomy": "frontal lobe", "laterality": "left", "urgency": "urgent", "status": "accepted",
        "model_id": "validated-module", "model_version": "1.0.0",
        "evidence": [EvidenceReference(series_id="series", instance_id="instance", frame=4)],
        "impression_clause": "Evidence-linked abnormality requiring radiologist correlation",
    }
    values.update(changes)
    return StructuredFinding(**values)


def test_composer_uses_only_accepted_evidence_linked_findings():
    result = StructuredAnalysisResult(findings=[finding(), finding(id="rejected", status="rejected", label="must not appear")], complete=False)
    findings, impression = compose_review_draft(result)
    assert "restricted diffusion" in findings
    assert "must not appear" not in findings
    assert "coverage was incomplete" in findings
    assert "Evidence-linked abnormality" in impression


def test_empty_result_never_claims_normality():
    findings, impression = compose_review_draft(StructuredAnalysisResult(findings=[], complete=True))
    assert "not a normal-study conclusion" in findings
    assert "Radiologist interpretation required" in impression


def test_accepted_finding_requires_resolved_laterality():
    with pytest.raises(ValidationError):
        finding(laterality="unknown")
