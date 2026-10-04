from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "controlled-pilot"


def test_evaluation_intended_use_is_explicit():
    text = (DOCS / "INTENDED_USE.md").read_text(encoding="utf-8")
    assert "CONTROLLED EVALUATION ONLY" in text
    assert "DE-IDENTIFIED DATA" in text
    assert "does not provide diagnoses" in text
    assert "Primary diagnosis" in text


def test_fixture_manifest_defaults_outside_clinical_data():
    manifest = json.loads((DOCS / "FIXTURE_PROVENANCE.template.json").read_text(encoding="utf-8"))
    assert manifest["clinical_data_root"] is False
    assert "evaluation" in manifest["allowed_use"]
    assert manifest["files"][0]["sha256"] == ""


def test_release_evidence_is_fail_closed():
    evidence = json.loads((DOCS / "release-evidence.template.json").read_text(encoding="utf-8"))
    assert evidence["decision"] == "NO_GO"
    assert evidence["environment"]["contains_phi"] is False
    assert evidence["gates"]
    assert all(gate["status"] == "NOT_RUN" for gate in evidence["gates"])
    assert all(not gate["evidence"] and not gate["reviewer"] for gate in evidence["gates"])


def test_production_compose_has_no_development_escape_hatch():
    compose = (ROOT / "ops" / "compose.yaml").read_text(encoding="utf-8")
    assert 'CLINICAL_DEV_MODE: "0"' in compose
    assert "sqlite://" not in compose
    assert "PACS_BEARER_TOKEN" not in compose
    assert "condition: service_healthy" in compose
    assert "no-new-privileges:true" in compose
    assert "internal: true" in compose
    assert "/ready" in compose
    migrate = compose.split("  migrate:", 1)[1].split("  web:", 1)[0]
    assert 'restart: "no"' in migrate
    assert "read_only: true" in migrate
    assert "tmpfs: [/tmp]" in migrate
    assert '["alembic", "-c", "alembic.ini", "upgrade", "head"]' in migrate


def test_deployment_assets_fail_closed_and_backup_binary_data_safely():
    compose = (ROOT / "ops" / "compose.yaml").read_text(encoding="utf-8")
    for setting in (
        "CLINICAL_TRUSTED_PROXY_MAX_AGE_SECONDS", "CLINICAL_MAX_DICOM_BYTES",
        "CLINICAL_MAX_IMPORT_FILES", "CLINICAL_MAX_IMPORT_BYTES",
    ):
        assert setting in compose

    nginx = (ROOT / "ops" / "docker" / "nginx.conf").read_text(encoding="utf-8")
    for header in ("User", "Role", "Institution", "Timestamp", "Signature"):
        assert f'X-Voxura-{header} ""' in nginx
    assert 'Cache-Control "private, no-store"' in nginx

    for script_name in ("backup.ps1", "restore.ps1"):
        script = (ROOT / "ops" / "scripts" / script_name).read_text(encoding="utf-8")
        assert "$LASTEXITCODE" in script
        assert "docker compose" in script
        assert "database:" in script
        assert "finally" in script

    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "ops/.env" in ignored
    assert "ops/backups/" in ignored


def test_production_schema_check_requires_alembic_revision():
    clinical = (ROOT / "backend" / "clinical.py").read_text(encoding="utf-8")
    baseline = (ROOT / "backend" / "migrations" / "versions" / "20260930_001_clinical_baseline.py").read_text(encoding="utf-8")
    reviewer = (ROOT / "backend" / "migrations" / "versions" / "20261004_002_reviewer_directory.py").read_text(encoding="utf-8")
    assert 'EXPECTED_ALEMBIC_REVISION = "20261004_002"' in clinical
    assert "SELECT version_num FROM alembic_version" in clinical
    assert 'revision = "20260930_001"' in baseline
    assert 'revision = "20261004_002"' in reviewer
    assert 'down_revision = "20260930_001"' in reviewer


def test_reviewer_migration_uses_alembic_connection():
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = ROOT / "backend" / "migrations" / "versions" / "20261004_002_reviewer_directory.py"
    spec = importlib.util.spec_from_file_location("reviewer_directory_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("reviewers")}
        indexes = {index["name"] for index in inspect(connection).get_indexes("reviewers")}
    assert {"id", "institution", "status", "added_by"} <= columns
    assert "reviewers_institution_idx" in indexes


def test_irreversible_baseline_has_restore_only_rollback_runbook():
    migration = (ROOT / "backend" / "migrations" / "versions" / "20260930_001_clinical_baseline.py").read_text(encoding="utf-8")
    rollback = (DOCS / "BACKUP_RESTORE_ROLLBACK.md").read_text(encoding="utf-8")
    assert "intentionally irreversible" in migration
    assert "restore" in rollback.lower()
    assert "not running `alembic downgrade`" in rollback


def test_supported_matrix_rejects_unvalidated_objects():
    matrix = (DOCS / "SUPPORTED_DICOM.md").read_text(encoding="utf-8")
    for item in ("Compressed transfer syntaxes", "Enhanced MR/CT or multi-frame", "Not supported", "Reject explicitly"):
        assert item in matrix
