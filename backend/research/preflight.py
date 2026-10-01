from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ResearchFixtureError(ValueError):
    """A public evaluation fixture is unsafe, incomplete, or not reproducible."""


@dataclass(frozen=True)
class ResearchFixture:
    manifest_path: Path
    data_root: Path
    mode: str
    payload: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_fixture(manifest_path: Path, clinical_data_root: Path) -> ResearchFixture:
    """Validate a public-case manifest without loading images, weights, or reports.

    The explicit external root prevents a fixture from being imported into the
    interactive clinical object store by accident.
    """
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"research_only", "source", "license_reviewed", "case_id", "split", "data_root", "mode", "artifacts"}
    missing = sorted(required - payload.keys())
    if missing:
        raise ResearchFixtureError(f"Manifest is missing: {', '.join(missing)}")
    if payload["research_only"] is not True or payload["source"] != "RadGenome-Brain MRI":
        raise ResearchFixtureError("Only an explicitly marked RadGenome-Brain research fixture is accepted")
    if payload["license_reviewed"] is not True:
        raise ResearchFixtureError("Dataset and model terms must be reviewed before any fixture is used")
    if payload["mode"] not in {"given-mask", "predicted-mask"}:
        raise ResearchFixtureError("mode must be given-mask or predicted-mask")
    data_root = Path(payload["data_root"]).expanduser().resolve()
    clinical_root = clinical_data_root.resolve()
    if data_root == clinical_root or clinical_root in data_root.parents:
        raise ResearchFixtureError("Research fixture data_root must be outside the clinical data root")
    for name, details in payload["artifacts"].items():
        if not {"path", "sha256"} <= details.keys():
            raise ResearchFixtureError(f"Artifact {name} requires path and sha256")
        path = (data_root / details["path"]).resolve()
        if data_root not in path.parents or not path.is_file():
            raise ResearchFixtureError(f"Artifact {name} is outside data_root or missing")
        if _sha256(path).lower() != str(details["sha256"]).lower():
            raise ResearchFixtureError(f"Artifact {name} checksum does not match")
    return ResearchFixture(manifest_path=manifest_path.resolve(), data_root=data_root, mode=payload["mode"], payload=payload)


def write_run_record(fixture: ResearchFixture, output_root: Path, *, model_id: str, model_sha256: str,
                     preprocessing_version: str, result: dict[str, Any]) -> Path:
    """Write an immutable, research-only run record; caller performs inference externally."""
    output_root = output_root.resolve()
    if fixture.data_root == output_root or fixture.data_root in output_root.parents:
        raise ResearchFixtureError("Evaluation output must not overwrite source fixture data")
    record = {
        "research_only": True,
        "source": fixture.payload["source"],
        "case_id": fixture.payload["case_id"],
        "split": fixture.payload["split"],
        "mode": fixture.mode,
        "model_id": model_id,
        "model_sha256": model_sha256,
        "preprocessing_version": preprocessing_version,
        "result": result,
    }
    encoded = json.dumps(record, indent=2, sort_keys=True) + "\n"
    record_id = hashlib.sha256(encoded.encode()).hexdigest()
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{record_id}.json"
    with target.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    return target
