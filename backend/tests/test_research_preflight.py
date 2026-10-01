import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from research.preflight import ResearchFixtureError, load_fixture, write_run_record


def manifest(tmp_path: Path, **changes):
    root = tmp_path / "fixture"; root.mkdir()
    image = root / "image.nii.gz"; image.write_bytes(b"deidentified-research-only")
    value = {"research_only": True, "source": "RadGenome-Brain MRI", "license_reviewed": True,
             "case_id": "held-out-case", "split": "test", "data_root": str(root), "mode": "given-mask",
             "artifacts": {"image": {"path": "image.nii.gz", "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}}}
    value.update(changes)
    path = tmp_path / "manifest.json"; path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_research_fixture_cannot_share_clinical_store(tmp_path):
    path = manifest(tmp_path)
    with pytest.raises(ResearchFixtureError, match="outside the clinical data root"):
        load_fixture(path, tmp_path)


def test_research_record_is_reproducible_and_write_once(tmp_path):
    fixture = load_fixture(manifest(tmp_path), tmp_path / "clinical")
    result = write_run_record(fixture, tmp_path / "evaluation", model_id="candidate", model_sha256="abc", preprocessing_version="1", result={"state": "abstained"})
    assert json.loads(result.read_text())["research_only"] is True
    with pytest.raises(FileExistsError):
        write_run_record(fixture, tmp_path / "evaluation", model_id="candidate", model_sha256="abc", preprocessing_version="1", result={"state": "abstained"})


def test_staging_command_requires_explicit_terms_confirmation(tmp_path):
    command = [sys.executable, "tools/stage_radgenome_fixture.py", "--manifest", str(manifest(tmp_path))]
    completed = subprocess.run(command, cwd=Path(__file__).parents[1], capture_output=True, text=True)
    assert completed.returncode != 0
    assert "accept-upstream-terms" in completed.stderr
