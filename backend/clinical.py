from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import jwt
import numpy as np
import pydicom
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from pydicom.pixels import apply_modality_lut, apply_voi_lut
from pydicom.uid import (
    CTImageStorage, ComputedRadiographyImageStorage, DigitalXRayImageStorageForPresentation,
    DigitalXRayImageStorageForProcessing, MRImageStorage,
)
from PIL import Image

DATA_ROOT = Path(os.getenv("CLINICAL_DATA_ROOT", Path(__file__).with_name("clinical_data")))
DB_PATH = DATA_ROOT / "clinical.db"
OBJECT_ROOT = DATA_ROOT / "objects"
DATABASE_URL = os.getenv("CLINICAL_DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}"
CLINICAL_ENV = os.getenv("CLINICAL_ENV", "development").lower()
JWT_SECRET = os.getenv("CLINICAL_JWT_SECRET", "development-only-change-me")
DEV_MODE = os.getenv("CLINICAL_DEV_MODE", "1" if CLINICAL_ENV == "development" else "0").lower() in {"1", "true", "yes"}
PACS_BASE_URL = os.getenv("PACS_DICOMWEB_URL", "").rstrip("/")
PACS_TOKEN = os.getenv("PACS_BEARER_TOKEN", "")
MAX_DICOM_BYTES = int(os.getenv("CLINICAL_MAX_DICOM_BYTES", str(512 * 1024 * 1024)))
MAX_IMPORT_FILES = int(os.getenv("CLINICAL_MAX_IMPORT_FILES", "2000"))
MAX_IMPORT_BYTES = int(os.getenv("CLINICAL_MAX_IMPORT_BYTES", str(2 * 1024 * 1024 * 1024)))
IMPORT_CHUNK_BYTES = 1024 * 1024
TRUSTED_PROXY_SECRET = os.getenv("CLINICAL_TRUSTED_PROXY_SECRET", "")
AUTH_MODE = os.getenv("CLINICAL_AUTH_MODE", "proxy" if CLINICAL_ENV == "production" else "jwt").lower()
TRUSTED_PROXY_MAX_AGE_SECONDS = int(os.getenv("CLINICAL_TRUSTED_PROXY_MAX_AGE_SECONDS", "60"))
QUALIFICATION_VERSION = "2026-09-29-stir-v1"
EXPECTED_ALEMBIC_REVISION = "20261004_002"
SUPPORTED_MODALITIES = {"CR", "DX", "CT", "MR"}
SUPPORTED_SOP_CLASSES = {
    str(ComputedRadiographyImageStorage), str(DigitalXRayImageStorageForPresentation),
    str(DigitalXRayImageStorageForProcessing), str(CTImageStorage), str(MRImageStorage),
}
ROLES = {"radiologist", "clinician", "technician", "administrator"}

if CLINICAL_ENV == "production":
    if DEV_MODE:
        raise RuntimeError("CLINICAL_DEV_MODE must be disabled in production")
    if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Production clinical storage requires PostgreSQL via CLINICAL_DATABASE_URL")
    if len(TRUSTED_PROXY_SECRET) < 32:
        raise RuntimeError("CLINICAL_TRUSTED_PROXY_SECRET must contain at least 32 characters in production")
    if AUTH_MODE != "proxy":
        raise RuntimeError("Production requires CLINICAL_AUTH_MODE=proxy")

if AUTH_MODE not in {"jwt", "proxy"}:
    raise RuntimeError("CLINICAL_AUTH_MODE must be jwt or proxy")

router = APIRouter(prefix="/v3", tags=["clinical-viewer"])


class _Database:
    def __init__(self, connection: Any, postgres: bool):
        self.connection = connection
        self.postgres = postgres

    def execute(self, sql: str, parameters: tuple[Any, ...] | list[Any] = ()):
        return self.connection.execute(sql.replace("?", "%s") if self.postgres else sql, parameters)

    def executescript(self, script: str) -> None:
        if not self.postgres:
            self.connection.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self.connection.execute(statement)


@contextmanager
def _db():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    postgres = DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://"))
    if postgres:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL clinical storage requires psycopg") from exc
        connection = psycopg.connect(DATABASE_URL.replace("postgresql+psycopg://", "postgresql://"), row_factory=dict_row)
    else:
        connection = sqlite3.connect(DB_PATH, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
    database = _Database(connection, postgres)
    try:
        yield database
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _add_column_if_missing(connection: _Database, table: str, column: str, definition: str) -> None:
    if connection.postgres:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        return
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize_clinical_store() -> None:
    OBJECT_ROOT.mkdir(parents=True, exist_ok=True)
    audit_id = "BIGSERIAL PRIMARY KEY" if DATABASE_URL.startswith("postgresql") else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with _db() as connection:
        connection.executescript(f"""
        CREATE TABLE IF NOT EXISTS studies (
            id TEXT PRIMARY KEY, institution TEXT NOT NULL, study_uid TEXT NOT NULL,
            patient_name TEXT NOT NULL, patient_id TEXT NOT NULL, birth_date TEXT, sex TEXT,
            accession TEXT, study_date TEXT, description TEXT, modalities TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unread', created_at DOUBLE PRECISION NOT NULL,
            UNIQUE(institution, study_uid)
        );
        CREATE TABLE IF NOT EXISTS series (
            id TEXT PRIMARY KEY, study_id TEXT NOT NULL, series_uid TEXT NOT NULL,
            modality TEXT NOT NULL, series_number INTEGER, description TEXT, laterality TEXT,
            rows INTEGER, columns INTEGER, created_at DOUBLE PRECISION NOT NULL,
            FOREIGN KEY(study_id) REFERENCES studies(id), UNIQUE(study_id, series_uid)
        );
        CREATE TABLE IF NOT EXISTS instances (
            id TEXT PRIMARY KEY, series_id TEXT NOT NULL, sop_uid TEXT NOT NULL,
            instance_number INTEGER, frame_count INTEGER NOT NULL, transfer_syntax TEXT,
            object_path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
            FOREIGN KEY(series_id) REFERENCES series(id), UNIQUE(series_id, sop_uid)
        );
        CREATE TABLE IF NOT EXISTS presentation_states (
            study_id TEXT NOT NULL, user_id TEXT NOT NULL, institution TEXT NOT NULL,
            state_json TEXT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(study_id,user_id,institution)
        );
        CREATE TABLE IF NOT EXISTS reports (
            study_id TEXT NOT NULL, institution TEXT NOT NULL, status TEXT NOT NULL,
            text TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY(study_id,institution)
        );
        CREATE TABLE IF NOT EXISTS model_registry (
            id TEXT PRIMARY KEY, display_name TEXT NOT NULL, version TEXT NOT NULL,
            status TEXT NOT NULL, intended_use TEXT NOT NULL, required_sequences_json TEXT NOT NULL,
            jurisdictions_json TEXT NOT NULL, license TEXT NOT NULL, checksum TEXT,
            enabled INTEGER NOT NULL DEFAULT 0, updated_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            id TEXT PRIMARY KEY, institution TEXT NOT NULL, study_id TEXT NOT NULL,
            profile TEXT NOT NULL, prior_study_id TEXT, idempotency_key TEXT NOT NULL,
            state TEXT NOT NULL, manifest_json TEXT NOT NULL, modules_json TEXT NOT NULL,
            message TEXT NOT NULL, requested_by TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL, UNIQUE(institution,idempotency_key),
            FOREIGN KEY(study_id) REFERENCES studies(id)
        );
        CREATE TABLE IF NOT EXISTS analysis_results (
            id TEXT PRIMARY KEY, institution TEXT NOT NULL, study_id TEXT NOT NULL,
            job_id TEXT NOT NULL, result_json TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL,
            FOREIGN KEY(study_id) REFERENCES studies(id), FOREIGN KEY(job_id) REFERENCES analysis_jobs(id)
        );
        CREATE TABLE IF NOT EXISTS report_drafts (
            study_id TEXT NOT NULL, institution TEXT NOT NULL, version INTEGER NOT NULL,
            status TEXT NOT NULL, findings_text TEXT NOT NULL, impression_text TEXT NOT NULL,
            updated_by TEXT NOT NULL, updated_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY(study_id,institution)
        );
        CREATE TABLE IF NOT EXISTS report_draft_history (
            id TEXT PRIMARY KEY, study_id TEXT NOT NULL, institution TEXT NOT NULL,
            version INTEGER NOT NULL, state_json TEXT NOT NULL, changed_by TEXT NOT NULL,
            changed_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviewers (
            id TEXT PRIMARY KEY, institution TEXT NOT NULL, name TEXT NOT NULL,
            affiliation TEXT NOT NULL, expertise TEXT NOT NULL, source_url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed', added_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id {audit_id}, timestamp DOUBLE PRECISION NOT NULL, institution TEXT NOT NULL,
            user_id TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL,
            resource_type TEXT NOT NULL, resource_id TEXT, outcome TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY, applied_at DOUBLE PRECISION NOT NULL
        );
        """)
        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(?,?) ON CONFLICT(version) DO NOTHING", ("001-clinical-baseline", time.time()))
        _add_column_if_missing(connection, "studies", "institution", "TEXT NOT NULL DEFAULT 'DEMO'")
        _add_column_if_missing(connection, "audit_events", "institution", "TEXT NOT NULL DEFAULT 'DEMO'")
        _add_column_if_missing(connection, "instances", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
        _add_column_if_missing(connection, "presentation_states", "version", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(connection, "presentation_states", "institution", "TEXT NOT NULL DEFAULT 'DEMO'")
        _add_column_if_missing(connection, "reports", "institution", "TEXT NOT NULL DEFAULT 'DEMO'")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS presentation_state_tenant_key ON presentation_states(study_id,user_id,institution)")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS report_tenant_key ON reports(study_id,institution)")
        if not connection.postgres:
            # The application never updates or deletes audit events. These guards make
            # accidental local mutation visible during development and tests.
            connection.executescript("""
            CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
            BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
            BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
            """)
        else:
            connection.execute("""
                CREATE OR REPLACE FUNCTION reject_audit_event_mutation() RETURNS trigger AS $$
                BEGIN RAISE EXCEPTION 'audit events are immutable'; END;
                $$ LANGUAGE plpgsql
            """)
            connection.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events")
            connection.execute("""
                CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
                FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
            """)
            connection.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events")
            connection.execute("""
                CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
                FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
            """)
        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(?,?) ON CONFLICT(version) DO NOTHING", ("002-instance-provenance-and-audit-guards", time.time()))
        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(?,?) ON CONFLICT(version) DO NOTHING", ("003-presentation-version", time.time()))
        now = time.time()
        models = (
            ("autorg-brain-rgv2", "AutoRG-Brain RGv2", "research", "candidate", "Offline grounded brain MRI report-generation challenger", ["T1", "T1C", "T2", "FLAIR", "DWI", "ADC"], [], "research-only; verify upstream terms", None, 0),
            ("monai-brats", "MONAI BraTS segmentation", "pinned-at-deployment", "candidate", "Research baseline for brain-tumor segmentation", ["T1", "T1C", "T2", "FLAIR"], [], "Apache-2.0 code; verify bundle/data terms", None, 0),
            ("siemens-airad-brain-mr", "AI-Rad Companion Brain MR", "K253057", "candidate", "Commercial morphometry and white-matter-hyperintensity candidate within labeled use", ["T1_MPRAGE", "FLAIR"], ["US"], "commercial", None, 0),
        )
        for model_id, name, version, status, intended_use, sequences, jurisdictions, license_name, checksum, enabled in models:
            connection.execute(
                "INSERT INTO model_registry(id,display_name,version,status,intended_use,required_sequences_json,jurisdictions_json,license,checksum,enabled,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                (model_id, name, version, status, intended_use, json.dumps(sequences), json.dumps(jurisdictions), license_name, checksum, enabled, now),
            )


def verify_clinical_schema() -> None:
    """Fail closed when the externally managed production schema is absent or stale."""
    try:
        with _db() as connection:
            marker = connection.execute(
                "SELECT version FROM schema_migrations WHERE version=?", ("003-presentation-version",)
            ).fetchone()
            alembic_revision = connection.execute(
                "SELECT version_num FROM alembic_version WHERE version_num=?",
                (EXPECTED_ALEMBIC_REVISION,),
            ).fetchone()
    except Exception as exc:
        raise RuntimeError(
            "Clinical database schema is unavailable; run Alembic before startup"
        ) from exc
    if not marker or not alembic_revision:
        raise RuntimeError(
            f"Clinical database migrations are not current; expected Alembic revision "
            f"{EXPECTED_ALEMBIC_REVISION}"
        )


def clinical_readiness() -> tuple[bool, dict[str, Any]]:
    checks: dict[str, Any] = {"database": False, "object_store": False, "environment": CLINICAL_ENV}
    try:
        with _db() as connection:
            connection.execute("SELECT 1").fetchone()
        checks["database"] = True
    except Exception:
        pass
    try:
        OBJECT_ROOT.mkdir(parents=True, exist_ok=True)
        checks["object_store"] = OBJECT_ROOT.is_dir() and os.access(OBJECT_ROOT, os.R_OK | os.W_OK)
    except OSError:
        pass
    ready = bool(checks["database"] and checks["object_store"])
    return ready, checks


class Principal(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    role: str
    institution: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")


class PresentationState(BaseModel):
    version: int = Field(0, ge=0)
    layout: Literal["1x1", "1x2", "2x2"] = "1x1"
    active_series_id: str | None = None
    active_instance_id: str | None = None
    frame: int = Field(0, ge=0)
    window_center: float | None = None
    window_width: float | None = Field(None, gt=0)
    zoom: float = Field(1.0, ge=0.1, le=20)
    pan_x: float = Field(0, ge=-10000, le=10000)
    pan_y: float = Field(0, ge=-10000, le=10000)
    rotation: Literal[0, 90, 180, 270] = 0
    inverted: bool = False
    annotations: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class AnalysisRequest(BaseModel):
    profile: Literal["brain_mri_assist_v1"] = "brain_mri_assist_v1"
    prior_study_id: str | None = None
    idempotency_key: str | None = Field(None, min_length=8, max_length=128)


class ReportDraftUpdate(BaseModel):
    version: int = Field(ge=0)
    findings_text: str = Field(max_length=20000)
    impression_text: str = Field(max_length=10000)


class ReviewChecklist(BaseModel):
    version: int = Field(ge=1)
    patient_identity_confirmed: bool
    laterality_checked: bool
    priors_checked: bool
    critical_findings_checked: bool
    warnings_resolved: bool


class ReviewerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    affiliation: str = Field(min_length=2, max_length=200)
    expertise: str = Field(min_length=2, max_length=200)
    source_url: str = Field(default="", max_length=500)


def _proxy_signature(user_id: str, role: str, institution: str, timestamp: str) -> str:
    payload = "\n".join((user_id, role, institution, timestamp)).encode("utf-8")
    return hmac.new(TRUSTED_PROXY_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _principal(
    authorization: Annotated[str | None, Header()] = None,
    proxy_user: Annotated[str | None, Header(alias="X-Voxura-User")] = None,
    proxy_role: Annotated[str | None, Header(alias="X-Voxura-Role")] = None,
    proxy_institution: Annotated[str | None, Header(alias="X-Voxura-Institution")] = None,
    proxy_timestamp: Annotated[str | None, Header(alias="X-Voxura-Timestamp")] = None,
    proxy_signature: Annotated[str | None, Header(alias="X-Voxura-Signature")] = None,
) -> Principal:
    if AUTH_MODE == "proxy":
        if not all((proxy_user, proxy_role, proxy_institution, proxy_timestamp, proxy_signature)):
            raise HTTPException(401, detail={"code": "trusted_identity_required", "message": "Authenticated proxy identity is required"})
        try:
            timestamp = int(proxy_timestamp)
        except (TypeError, ValueError) as exc:
            raise HTTPException(401, detail={"code": "invalid_proxy_identity", "message": "Proxy identity is invalid"}) from exc
        if abs(int(time.time()) - timestamp) > TRUSTED_PROXY_MAX_AGE_SECONDS:
            raise HTTPException(401, detail={"code": "stale_proxy_identity", "message": "Proxy identity has expired"})
        expected = _proxy_signature(proxy_user, proxy_role, proxy_institution, proxy_timestamp)
        if not hmac.compare_digest(proxy_signature, expected):
            raise HTTPException(401, detail={"code": "untrusted_proxy_identity", "message": "Proxy identity could not be verified"})
        try:
            principal = Principal(user_id=proxy_user, role=proxy_role, institution=proxy_institution)
        except ValueError as exc:
            raise HTTPException(401, detail={"code": "invalid_proxy_identity", "message": "Proxy identity is invalid"}) from exc
    else:
        if CLINICAL_ENV == "production":
            raise HTTPException(503, detail={"code": "production_auth_misconfigured", "message": "Production authentication is unavailable"})
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, detail={"code": "authentication_required", "message": "Sign in is required"})
        try:
            claims = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"], audience="clinical-viewer")
            principal = Principal(user_id=claims["sub"], role=claims["role"], institution=claims["institution"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise HTTPException(401, detail={"code": "invalid_session", "message": "The session is invalid or expired"}) from exc
    if principal.role not in ROLES:
        raise HTTPException(403, detail={"code": "invalid_role", "message": "The assigned role is not supported"})
    return principal


def _session_payload(principal: Principal) -> dict[str, Any]:
    return {
        "user": {"id": principal.user_id, "role": principal.role},
        "institution": principal.institution,
        "evaluation_only": True,
    }


def _audit(principal: Principal, action: str, resource_type: str, resource_id: str | None = None,
           outcome: str = "success", details: dict[str, Any] | None = None) -> None:
    with _db() as connection:
        connection.execute(
            "INSERT INTO audit_events(timestamp,institution,user_id,role,action,resource_type,resource_id,outcome,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (time.time(), principal.institution, principal.user_id, principal.role, action, resource_type, resource_id, outcome, json.dumps(details or {})),
        )


def _text(dataset: pydicom.Dataset, name: str, default: str = "") -> str:
    value = getattr(dataset, name, default)
    return str(value) if value is not None else default


def _integer(dataset: pydicom.Dataset, name: str) -> int | None:
    try:
        return int(getattr(dataset, name))
    except (AttributeError, TypeError, ValueError):
        return None


def _instance_metadata(dataset: pydicom.Dataset) -> dict[str, Any]:
    """Keep only rendering/qualification metadata; never copy free-text PHI fields."""
    scalar_names = (
        "ImageOrientationPatient", "ImagePositionPatient", "PixelSpacing", "SliceThickness",
        "SpacingBetweenSlices", "MagneticFieldStrength", "Manufacturer", "SeriesDescription",
        "ProtocolName", "AcquisitionDate", "AcquisitionTime", "FrameOfReferenceUID",
        "WindowCenter", "WindowWidth", "RescaleSlope", "RescaleIntercept",
        "PhotometricInterpretation", "BitsAllocated", "BitsStored", "HighBit", "PixelRepresentation",
    )
    metadata: dict[str, Any] = {}
    for name in scalar_names:
        value = getattr(dataset, name, None)
        if value is not None:
            metadata[name] = ([str(item) for item in value]
                              if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
                              else str(value))
    return metadata


def _validate_dicom_image(dataset: pydicom.Dataset) -> None:
    modality = _text(dataset, "Modality").upper()
    if modality not in SUPPORTED_MODALITIES:
        raise ValueError(f"Unsupported modality {modality or 'unknown'}")
    if str(getattr(dataset, "SOPClassUID", "")) not in SUPPORTED_SOP_CLASSES:
        raise ValueError("Unsupported DICOM SOP Class for clinical viewing")
    for field in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"):
        if not getattr(dataset, field, None):
            raise ValueError(f"Missing required {field}")
    if "PixelData" not in dataset:
        raise ValueError("DICOM object has no pixel data")
    rows, columns = _integer(dataset, "Rows"), _integer(dataset, "Columns")
    if not rows or not columns or rows < 1 or columns < 1:
        raise ValueError("DICOM image dimensions are invalid")
    if _integer(dataset, "SamplesPerPixel") != 1:
        raise ValueError("Only monochrome clinical images are currently supported")
    if _text(dataset, "PhotometricInterpretation").upper() not in {"MONOCHROME1", "MONOCHROME2"}:
        raise ValueError("Unsupported photometric interpretation")
    if _integer(dataset, "BitsAllocated") not in {8, 16}:
        raise ValueError("Unsupported pixel allocation; expected 8 or 16 bits")
    if int(getattr(dataset, "NumberOfFrames", 1) or 1) != 1:
        raise ValueError("Multi-frame DICOM objects are not enabled in this controlled pilot")
    transfer_syntax = getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", None)
    if not transfer_syntax:
        raise ValueError("Missing transfer syntax")
    if transfer_syntax.is_compressed:
        raise ValueError("Compressed transfer syntax is not enabled in this controlled pilot")


def _require_study(connection: _Database, study_id: str, principal: Principal):
    study = connection.execute("SELECT * FROM studies WHERE id=? AND institution=?", (study_id, principal.institution)).fetchone()
    if not study:
        raise HTTPException(404, detail={"code": "study_not_found", "message": "Study was not found"})
    return study


def _validate_uid(value: str, label: str) -> str:
    if not value or len(value) > 64 or any(char not in "0123456789." for char in value):
        raise HTTPException(422, detail={"code": "invalid_dicom_uid", "message": f"Invalid {label}"})
    return value


async def _pacs_get(path: str, principal: Principal, params: dict[str, Any] | None = None,
                    accept: str = "application/dicom+json") -> httpx.Response:
    if not PACS_BASE_URL:
        raise HTTPException(503, detail={"code": "pacs_not_configured", "message": "PACS connection is not configured"})
    headers = {"Accept": accept}
    if PACS_TOKEN:
        headers["Authorization"] = f"Bearer {PACS_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=15, verify=True, follow_redirects=False) as client:
            response = await client.get(f"{PACS_BASE_URL}{path}", params=params, headers=headers)
    except httpx.HTTPError as exc:
        _audit(principal, "pacs.retrieve", "pacs", outcome="failure")
        raise HTTPException(503, detail={"code": "pacs_unavailable", "message": "PACS is unreachable"}) from exc
    if response.status_code == 404:
        raise HTTPException(404, detail={"code": "pacs_resource_not_found", "message": "PACS resource was not found"})
    if not response.is_success:
        raise HTTPException(502, detail={"code": "pacs_request_failed", "message": "PACS could not complete the request"})
    return response


def _instance_path(instance_id: str, principal: Principal) -> Path:
    with _db() as connection:
        row = connection.execute(
            "SELECT i.object_path FROM instances i JOIN series s ON s.id=i.series_id JOIN studies st ON st.id=s.study_id WHERE i.id=? AND st.institution=?",
            (instance_id, principal.institution),
        ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "instance_not_found", "message": "Instance was not found"})
    return Path(row["object_path"])


@router.post("/session/dev")
def development_session() -> dict[str, Any]:
    if not DEV_MODE or AUTH_MODE != "jwt" or CLINICAL_ENV == "production":
        raise HTTPException(404, detail="Not found")
    now = int(time.time())
    token = jwt.encode({"sub": "demo-radiologist", "role": "radiologist", "institution": "DEMO",
                        "aud": "clinical-viewer", "iat": now, "exp": now + 8 * 60 * 60}, JWT_SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": 8 * 60 * 60,
            "user": {"id": "demo-radiologist", "display_name": "Demo Radiologist", "role": "radiologist"}}


@router.get("/session")
def current_session(principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    return _session_payload(principal)


@router.get("/pacs/health")
async def pacs_health(principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    if not PACS_BASE_URL:
        return {"configured": False, "reachable": False, "message": "PACS connection is not configured"}
    headers = {"Authorization": f"Bearer {PACS_TOKEN}"} if PACS_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=5, verify=True) as client:
            response = await client.get(f"{PACS_BASE_URL}/studies", params={"limit": 1}, headers=headers)
        reachable = response.status_code < 500
        message = "Connected" if response.is_success else f"PACS returned {response.status_code}"
    except httpx.HTTPError:
        reachable, message = False, "PACS is unreachable"
    _audit(principal, "pacs.health", "pacs", outcome="success" if reachable else "failure")
    return {"configured": True, "reachable": reachable, "message": message}


@router.get("/pacs/qido/studies")
async def qido_studies(principal: Annotated[Principal, Depends(_principal)], patient_name: str = "",
                       accession_number: str = "", modality: str = "", limit: int = Query(25, ge=1, le=100),
                       offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if patient_name: params["PatientName"] = patient_name
    if accession_number: params["AccessionNumber"] = accession_number
    if modality: params["ModalitiesInStudy"] = modality
    response = await _pacs_get("/studies", principal, params)
    _audit(principal, "pacs.qido.search", "study", details={"result_count": len(response.json())})
    return response.json()


@router.get("/pacs/qido/studies/{study_uid}/series")
async def qido_series(study_uid: str, principal: Annotated[Principal, Depends(_principal)]) -> list[dict[str, Any]]:
    response = await _pacs_get(f"/studies/{_validate_uid(study_uid, 'study UID')}/series", principal)
    _audit(principal, "pacs.qido.series", "study")
    return response.json()


@router.get("/pacs/wado/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/metadata")
async def wado_metadata(study_uid: str, series_uid: str, sop_uid: str,
                        principal: Annotated[Principal, Depends(_principal)]) -> list[dict[str, Any]]:
    path = "/studies/{}/series/{}/instances/{}/metadata".format(
        _validate_uid(study_uid, "study UID"), _validate_uid(series_uid, "series UID"), _validate_uid(sop_uid, "instance UID")
    )
    response = await _pacs_get(path, principal)
    _audit(principal, "pacs.wado.metadata", "instance")
    return response.json()


@router.post("/import", status_code=201)
async def import_dicom(files: list[UploadFile] = File(...), principal: Principal = Depends(_principal)) -> dict[str, Any]:
    if principal.role not in {"radiologist", "technician", "administrator"}:
        raise HTTPException(403, detail={"code": "import_forbidden", "message": "Your role cannot import studies"})
    if len(files) > MAX_IMPORT_FILES:
        raise HTTPException(413, detail={"code": "too_many_files", "message": f"At most {MAX_IMPORT_FILES} files may be imported at once"})
    accepted, rejected = [], []
    total_bytes = 0
    staging_root = OBJECT_ROOT / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    for upload in files:
        staging_path: Path | None = None
        final_path: Path | None = None
        try:
            digest_builder = hashlib.sha256()
            file_bytes = 0
            descriptor, staging_name = tempfile.mkstemp(prefix="dicom-", suffix=".part", dir=staging_root)
            staging_path = Path(staging_name)
            with os.fdopen(descriptor, "wb") as staged:
                while chunk := await upload.read(IMPORT_CHUNK_BYTES):
                    file_bytes += len(chunk)
                    total_bytes += len(chunk)
                    if file_bytes > MAX_DICOM_BYTES:
                        raise ValueError("File exceeds the configured DICOM size limit")
                    if total_bytes > MAX_IMPORT_BYTES:
                        raise ValueError("Import exceeds the configured total byte limit")
                    digest_builder.update(chunk)
                    staged.write(chunk)
                staged.flush()
                os.fsync(staged.fileno())
            if file_bytes == 0:
                raise ValueError("DICOM file is empty")
            dataset = pydicom.dcmread(staging_path, force=False, stop_before_pixels=False)
            modality = _text(dataset, "Modality").upper()
            _validate_dicom_image(dataset)
            digest = digest_builder.hexdigest()
            study_uid, series_uid, sop_uid = map(str, (dataset.StudyInstanceUID, dataset.SeriesInstanceUID, dataset.SOPInstanceUID))
            now = time.time()
            with _db() as connection:
                study = connection.execute("SELECT id FROM studies WHERE study_uid=? AND institution=?", (study_uid, principal.institution)).fetchone()
                study_id = study["id"] if study else uuid.uuid4().hex
                if not study:
                    connection.execute(
                        "INSERT INTO studies(id,institution,study_uid,patient_name,patient_id,birth_date,sex,accession,study_date,description,modalities,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (study_id, principal.institution, study_uid, _text(dataset, "PatientName", "Unknown"), _text(dataset, "PatientID", "Unknown"),
                         _text(dataset, "PatientBirthDate"), _text(dataset, "PatientSex"), _text(dataset, "AccessionNumber"),
                         _text(dataset, "StudyDate"), _text(dataset, "StudyDescription", "Imaging study"), modality, "unread", now),
                    )
                else:
                    current = connection.execute("SELECT modalities FROM studies WHERE id=?", (study_id,)).fetchone()["modalities"]
                    if modality not in current.split("\\"):
                        connection.execute("UPDATE studies SET modalities=? WHERE id=?", (f"{current}\\{modality}", study_id))
                series = connection.execute("SELECT id FROM series WHERE series_uid=? AND study_id=?", (series_uid, study_id)).fetchone()
                series_id = series["id"] if series else uuid.uuid4().hex
                if not series:
                    connection.execute(
                        "INSERT INTO series(id,study_id,series_uid,modality,series_number,description,laterality,rows,columns,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (series_id, study_id, series_uid, modality, _integer(dataset, "SeriesNumber"),
                         _text(dataset, "SeriesDescription", f"{modality} series"), _text(dataset, "ImageLaterality", _text(dataset, "Laterality")),
                         _integer(dataset, "Rows"), _integer(dataset, "Columns"), now),
                    )
                existing = connection.execute("SELECT id,sha256 FROM instances WHERE sop_uid=? AND series_id=?", (sop_uid, series_id)).fetchone()
                if existing and existing["sha256"] != digest:
                    raise ValueError("SOP Instance UID collision: stored source hash differs from the uploaded object")
                instance_id = existing["id"] if existing else uuid.uuid4().hex
                if not existing:
                    final_path = OBJECT_ROOT / principal.institution / study_id / f"{instance_id}.dcm"
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staging_path, final_path)
                    staging_path = None
                    transfer_syntax = str(getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", ""))
                    connection.execute(
                        "INSERT INTO instances(id,series_id,sop_uid,instance_number,frame_count,transfer_syntax,object_path,sha256,created_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (instance_id, series_id, sop_uid, _integer(dataset, "InstanceNumber"), int(getattr(dataset, "NumberOfFrames", 1)),
                         transfer_syntax, str(final_path), digest, now, json.dumps(_instance_metadata(dataset))),
                    )
            accepted.append({"filename": upload.filename, "status": "duplicate" if existing else "imported",
                             "bytes": file_bytes, "sha256": digest, "study_id": study_id,
                             "series_id": series_id, "instance_id": instance_id})
        except (ValueError, pydicom.errors.InvalidDicomError) as exc:
            if final_path is not None and final_path.exists():
                final_path.unlink(missing_ok=True)
            rejected.append({"filename": upload.filename, "status": "rejected", "code": "invalid_dicom",
                             "reason": str(exc)[:240]})
        except Exception:
            if final_path is not None and final_path.exists():
                final_path.unlink(missing_ok=True)
            rejected.append({"filename": upload.filename, "status": "rejected", "code": "import_failed",
                             "reason": "The file could not be imported; contact an administrator with the request ID"})
        finally:
            if staging_path is not None:
                staging_path.unlink(missing_ok=True)
            await upload.close()
    _audit(principal, "dicom.import", "study", details={"accepted": len(accepted), "rejected": len(rejected)})
    return {"accepted": accepted, "rejected": rejected, "limits": {
        "file_bytes": MAX_DICOM_BYTES, "total_bytes": MAX_IMPORT_BYTES, "files": MAX_IMPORT_FILES,
    }}


@router.get("/studies")
def studies(principal: Annotated[Principal, Depends(_principal)], patient: str = "", accession: str = "",
            modality: str = "", date_from: str = "", date_to: str = "", status: str = "",
            limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    clauses, values = ["institution=?"], [principal.institution]
    for clause, value in (("patient_name LIKE ? OR patient_id LIKE ?", patient), ("accession LIKE ?", accession),
                          ("modalities LIKE ?", modality), ("status=?", status)):
        if value:
            clauses.append(f"({clause})")
            wildcard = f"%{value}%"
            values.extend([wildcard, wildcard] if clause.startswith("patient") else ([value] if clause == "status=?" else [wildcard]))
    if date_from:
        clauses.append("study_date>=?"); values.append(date_from)
    if date_to:
        clauses.append("study_date<=?"); values.append(date_to)
    where = " AND ".join(clauses)
    with _db() as connection:
        total = connection.execute(f"SELECT COUNT(*) AS count FROM studies WHERE {where}", tuple(values)).fetchone()["count"]
        rows = connection.execute(f"SELECT id,patient_name,patient_id,birth_date,sex,accession,study_date,description,modalities,status FROM studies WHERE {where} ORDER BY study_date DESC LIMIT ? OFFSET ?", (*values, limit, offset)).fetchall()
    _audit(principal, "study.search", "study", details={"result_count": len(rows)})
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/studies/{study_id}/series")
def study_series(study_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        rows = connection.execute("SELECT s.id,s.modality,s.series_number,s.description,s.laterality,s.rows,s.columns,COUNT(i.id) instance_count,COALESCE(SUM(i.frame_count),0) frame_count FROM series s LEFT JOIN instances i ON i.series_id=s.id WHERE s.study_id=? GROUP BY s.id,s.modality,s.series_number,s.description,s.laterality,s.rows,s.columns ORDER BY s.series_number", (study_id,)).fetchall()
    _audit(principal, "study.open", "study", study_id)
    return {"items": [dict(row) for row in rows]}


@router.get("/studies/{study_id}/series/{series_id}/metadata")
def series_metadata(study_id: str, series_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        study = _require_study(connection, study_id, principal)
        series = connection.execute("SELECT * FROM series WHERE id=? AND study_id=?", (series_id, study_id)).fetchone()
        if not series:
            raise HTTPException(404, detail={"code": "series_not_found", "message": "Series was not found"})
        instances = connection.execute("SELECT id,instance_number,frame_count,transfer_syntax FROM instances WHERE series_id=? ORDER BY instance_number", (series_id,)).fetchall()
    return {"study": {key: study[key] for key in ("id", "patient_name", "patient_id", "birth_date", "sex", "accession", "study_date", "description", "modalities")},
            "series": dict(series), "instances": [dict(row) for row in instances]}


def _float_vector(metadata: dict[str, Any], name: str, size: int) -> list[float] | None:
    value = metadata.get(name)
    if not isinstance(value, list) or len(value) != size:
        return None
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    return result if all(np.isfinite(result)) else None


def _valid_orientation(metadata: dict[str, Any], tolerance: float = 0.02) -> list[float] | None:
    orientation = _float_vector(metadata, "ImageOrientationPatient", 6)
    if orientation is None:
        return None
    row = np.asarray(orientation[:3], dtype=float)
    column = np.asarray(orientation[3:], dtype=float)
    if abs(float(np.linalg.norm(row)) - 1.0) > tolerance:
        return None
    if abs(float(np.linalg.norm(column)) - 1.0) > tolerance:
        return None
    if abs(float(np.dot(row, column))) > tolerance:
        return None
    return orientation


def _valid_pixel_spacing(value: Any) -> list[float] | None:
    spacing = _float_vector({"spacing": value}, "spacing", 2)
    if spacing is None or any(component <= 0 for component in spacing):
        return None
    return spacing


def _consistent_pixel_spacing(values: list[Any]) -> bool:
    spacings = [_valid_pixel_spacing(value) for value in values]
    if not spacings or any(value is None for value in spacings):
        return False
    reference = np.asarray(spacings[0])
    return all(np.allclose(reference, np.asarray(value), rtol=1e-4, atol=1e-6) for value in spacings[1:])


def _geometry_position(metadata: dict[str, Any]) -> float | None:
    orientation = _valid_orientation(metadata)
    position = _float_vector(metadata, "ImagePositionPatient", 3)
    if orientation is None or position is None:
        return None
    normal = np.cross(np.asarray(orientation[:3]), np.asarray(orientation[3:]))
    norm = float(np.linalg.norm(normal))
    if norm < 1e-6:
        return None
    return float(np.dot(np.asarray(position), normal / norm))


@router.get("/studies/{study_id}/viewer-manifest")
def viewer_manifest(study_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        study = _require_study(connection, study_id, principal)
        series_rows = connection.execute(
            "SELECT id,modality,series_number,description,laterality,rows,columns FROM series WHERE study_id=? ORDER BY series_number,id",
            (study_id,),
        ).fetchall()
        payload: list[dict[str, Any]] = []
        study_warnings: list[str] = []
        for series in series_rows:
            rows = connection.execute(
                "SELECT id,instance_number,frame_count,transfer_syntax,sha256,metadata_json FROM instances WHERE series_id=?",
                (series["id"],),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                metadata = json.loads(row["metadata_json"] or "{}")
                items.append({
                    "id": row["id"], "instance_number": row["instance_number"],
                    "frame_count": row["frame_count"], "transfer_syntax": row["transfer_syntax"],
                    "sha256": row["sha256"], "geometry_position": _geometry_position(metadata),
                    "orientation": metadata.get("ImageOrientationPatient"),
                    "position": metadata.get("ImagePositionPatient"),
                    "pixel_spacing": metadata.get("PixelSpacing"),
                    "window_center": metadata.get("WindowCenter"), "window_width": metadata.get("WindowWidth"),
                    "photometric_interpretation": metadata.get("PhotometricInterpretation"),
                    "dicom_url": f"/v3/instances/{row['id']}/dicom",
                })
            valid_orientations = [_valid_orientation({"ImageOrientationPatient": item["orientation"]}) for item in items]
            orientation_consistent = bool(valid_orientations) and all(value is not None for value in valid_orientations)
            if orientation_consistent:
                reference = np.asarray(valid_orientations[0])
                orientation_consistent = all(np.allclose(reference, np.asarray(value), rtol=0, atol=0.02) for value in valid_orientations[1:])
            geometry_complete = bool(items) and orientation_consistent and all(item["geometry_position"] is not None for item in items)
            if geometry_complete:
                items.sort(key=lambda item: (item["geometry_position"], item["instance_number"] or 0, item["id"]))
                ordering = "patient_geometry"
            else:
                items.sort(key=lambda item: (item["instance_number"] is None, item["instance_number"] or 0, item["id"]))
                ordering = "instance_number_fallback"
            warnings: list[str] = []
            if not geometry_complete:
                warnings.append("Spatial geometry is incomplete; instance-number fallback ordering is in use")
            numbers = [item["instance_number"] for item in items if item["instance_number"] is not None]
            if len(numbers) != len(set(numbers)):
                warnings.append("Duplicate instance numbers were detected")
            if numbers and max(numbers) - min(numbers) + 1 != len(set(numbers)):
                warnings.append("Instance-number gaps were detected; the series may be incomplete")
            spacing_valid = _consistent_pixel_spacing([item["pixel_spacing"] for item in items])
            if not spacing_valid:
                warnings.append("Pixel spacing is missing or invalid; calibrated measurements are disabled")
            study_warnings.extend(f"Series {series['id']}: {warning}" for warning in warnings)
            payload.append({"id": series["id"], "modality": series["modality"],
                            "series_number": series["series_number"], "description": series["description"],
                            "laterality": series["laterality"], "rows": series["rows"], "columns": series["columns"],
                            "instance_count": len(items),
                            "frame_count": sum(int(item["frame_count"]) for item in items),
                            "ordering": ordering, "complete": not warnings, "has_pixel_spacing": spacing_valid,
                            "measurement_calibrated": spacing_valid,
                            "warnings": warnings, "instances": items})
    _audit(principal, "viewer.manifest", "study", study_id, details={"series_count": len(payload)})
    return {"study": {key: study[key] for key in ("id", "patient_name", "patient_id", "birth_date", "sex", "accession", "study_date", "description", "modalities")},
            "evaluation_only": True, "source_pixels_immutable": True,
            "complete": bool(payload) and not study_warnings, "warnings": study_warnings, "series": payload}


@router.get("/instances/{instance_id}/dicom")
def raw_instance(instance_id: str, principal: Annotated[Principal, Depends(_principal)]) -> FileResponse:
    path = _instance_path(instance_id, principal)
    if not path.is_file():
        raise HTTPException(410, detail={"code": "source_object_missing", "message": "The immutable source object is unavailable"})
    _audit(principal, "instance.retrieve", "instance", instance_id)
    return FileResponse(path, media_type="application/dicom", filename=f"{instance_id}.dcm",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                                 "X-Source-Immutable": "true"})


@router.get("/instances/{instance_id}/frames/{frame}/rendered")
def rendered_frame(instance_id: str, frame: int, principal: Annotated[Principal, Depends(_principal)],
                   window_center: float | None = None, window_width: float | None = Query(None, gt=0), invert: bool = False) -> Response:
    dataset = pydicom.dcmread(_instance_path(instance_id, principal))
    try:
        pixels = dataset.pixel_array
    except Exception as exc:
        raise HTTPException(422, detail={"code": "unsupported_transfer_syntax", "message": "This image compression is not available on the server"}) from exc
    if pixels.ndim >= 3 and int(getattr(dataset, "NumberOfFrames", 1)) > 1:
        if frame < 0 or frame >= pixels.shape[0]:
            raise HTTPException(404, detail={"code": "frame_not_found", "message": "Frame was not found"})
        pixels = pixels[frame]
    elif frame != 0:
        raise HTTPException(404, detail={"code": "frame_not_found", "message": "Frame was not found"})
    values = apply_modality_lut(pixels, dataset).astype(np.float32)
    if window_center is not None and window_width is not None:
        low, high = window_center - window_width / 2, window_center + window_width / 2
    else:
        try:
            values = np.asarray(apply_voi_lut(values, dataset), dtype=np.float32)
        except Exception:
            pass
        low, high = float(np.nanmin(values)), float(np.nanmax(values))
    image = np.zeros(values.shape[-2:], dtype=np.uint8) if not np.isfinite(low) or not np.isfinite(high) or high <= low else np.clip((values - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)
    if (_text(dataset, "PhotometricInterpretation") == "MONOCHROME1") ^ invert:
        image = 255 - image
    output = io.BytesIO(); Image.fromarray(image).save(output, "PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Source-Immutable": "true"})


@router.get("/studies/{study_id}/presentation-state")
def get_presentation_state(study_id: str, principal: Annotated[Principal, Depends(_principal)]) -> PresentationState:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        row = connection.execute(
            "SELECT state_json,version FROM presentation_states WHERE study_id=? AND user_id=? AND institution=?",
            (study_id, principal.user_id, principal.institution),
        ).fetchone()
    if not row:
        return PresentationState()
    state = PresentationState.model_validate_json(row["state_json"])
    return state.model_copy(update={"version": int(row["version"])})


@router.put("/studies/{study_id}/presentation-state")
def put_presentation_state(study_id: str, state: PresentationState, principal: Annotated[Principal, Depends(_principal)]) -> PresentationState:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        if state.active_series_id:
            series = connection.execute(
                "SELECT id FROM series WHERE id=? AND study_id=?", (state.active_series_id, study_id)
            ).fetchone()
            if not series:
                raise HTTPException(422, detail={"code": "invalid_presentation_series",
                                                 "message": "The saved series does not belong to this study"})
        if state.active_instance_id:
            instance = connection.execute(
                "SELECT i.id,i.series_id FROM instances i JOIN series s ON s.id=i.series_id "
                "WHERE i.id=? AND s.study_id=?", (state.active_instance_id, study_id)
            ).fetchone()
            if not instance or (state.active_series_id and instance["series_id"] != state.active_series_id):
                raise HTTPException(422, detail={"code": "invalid_presentation_instance",
                                                 "message": "The saved image does not belong to the selected study series"})
        if state.annotations:
            if not state.active_series_id:
                raise HTTPException(422, detail={"code": "uncalibrated_annotation",
                                                 "message": "Measurements require a selected calibrated series"})
            spacing_rows = connection.execute(
                "SELECT metadata_json FROM instances WHERE series_id=?", (state.active_series_id,)
            ).fetchall()
            spacings = [json.loads(row["metadata_json"] or "{}").get("PixelSpacing") for row in spacing_rows]
            if not _consistent_pixel_spacing(spacings):
                raise HTTPException(422, detail={"code": "uncalibrated_annotation",
                                                 "message": "Measurements cannot be saved without pixel spacing"})
        current = connection.execute(
            "SELECT version FROM presentation_states WHERE study_id=? AND user_id=? AND institution=?",
            (study_id, principal.user_id, principal.institution),
        ).fetchone()
        current_version = int(current["version"]) if current else 0
        if state.version != current_version:
            raise HTTPException(409, detail={"code": "presentation_state_conflict",
                                             "message": "Presentation state changed in another session; reload before saving"})
        saved = state.model_copy(update={"version": current_version + 1})
        connection.execute(
            "INSERT INTO presentation_states(study_id,user_id,institution,state_json,updated_at,version) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(study_id,user_id,institution) DO UPDATE SET "
            "state_json=excluded.state_json,"
            "updated_at=excluded.updated_at,version=excluded.version",
            (study_id, principal.user_id, principal.institution, saved.model_dump_json(), time.time(), saved.version),
        )
    _audit(principal, "presentation.update", "study", study_id)
    return saved


@router.get("/studies/{study_id}/report")
def study_report(study_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        row = connection.execute(
            "SELECT status,text,updated_at FROM reports WHERE study_id=? AND institution=?",
            (study_id, principal.institution),
        ).fetchone()
    return dict(row) if row else {"status": "unavailable", "text": "No signed report is available for this study.", "updated_at": None}


def _sequence_manifest(connection: _Database, study_id: str) -> dict[str, Any]:
    rows = connection.execute("SELECT id,modality,description,rows,columns FROM series WHERE study_id=? ORDER BY series_number", (study_id,)).fetchall()
    detected: set[str] = set()
    for row in rows:
        text = f"{row['modality']} {row['description'] or ''}".upper().replace("-", "")
        aliases_by_name = {"T1C": ("T1C", "T1 POST", "T1+", "MPRAGE+C"), "FLAIR": ("FLAIR",), "DWI": ("DWI", "DIFF"), "ADC": ("ADC",), "SWI": ("SWI", "SUSCEPT"), "STIR": ("STIR",), "T2": ("T2",), "T1": ("T1", "MPRAGE")}
        for name, aliases in aliases_by_name.items():
            if any(alias in text for alias in aliases):
                detected.add(name)
    warnings = ["Sequence classification is metadata-derived and requires radiologist confirmation"]
    series_payload = []
    for row in rows:
        instances = connection.execute("SELECT metadata_json,frame_count FROM instances WHERE series_id=?", (row["id"],)).fetchall()
        metadata = [json.loads(item["metadata_json"] or "{}") for item in instances]
        has_geometry = any("ImageOrientationPatient" in item and "ImagePositionPatient" in item for item in metadata)
        has_spacing = any("PixelSpacing" in item for item in metadata)
        if row["modality"] in {"CT", "MR"} and not has_geometry:
            warnings.append(f"Series {row['id']} has incomplete spatial orientation metadata")
        if not has_spacing:
            warnings.append(f"Series {row['id']} has no pixel-spacing metadata; calibrated measurements are unavailable")
        series_payload.append({"id": row["id"], "description": row["description"], "rows": row["rows"], "columns": row["columns"],
                               "instance_count": len(instances), "has_geometry": has_geometry, "has_pixel_spacing": has_spacing})
    return {"series_count": len(rows), "sequences": sorted(detected), "series": series_payload,
            "warnings": list(dict.fromkeys(warnings))}


@router.get("/ai/capabilities")
def ai_capabilities(principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        rows = connection.execute("SELECT * FROM model_registry ORDER BY display_name").fetchall()
    models = []
    for row in rows:
        item = dict(row)
        item["required_sequences"] = json.loads(item.pop("required_sequences_json"))
        item["jurisdictions"] = json.loads(item.pop("jurisdictions_json"))
        item["enabled"] = bool(item["enabled"])
        models.append(item)
    return {"intended_use": "Radiologist-assist research foundation; not autonomous diagnosis",
            "worker": {"configured": False, "backend": "qualification-only"}, "profiles": ["brain_mri_assist_v1"], "models": models,
            "safety": {"automatic_signing": False, "generic_diagnosis_endpoint": False, "abstention_required": True}}


def _job_payload(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["manifest"] = json.loads(item.pop("manifest_json"))
    item["modules"] = json.loads(item.pop("modules_json"))
    for key in ("institution", "idempotency_key", "requested_by"):
        item.pop(key, None)
    return item


@router.post("/studies/{study_id}/analysis-jobs", status_code=202)
def create_analysis_job(study_id: str, request: AnalysisRequest, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    if principal.role not in {"radiologist", "administrator"}:
        raise HTTPException(403, detail={"code": "analysis_forbidden", "message": "Only radiologists and administrators can request analysis"})
    now = time.time()
    with _db() as connection:
        study = _require_study(connection, study_id, principal)
        if request.prior_study_id:
            _require_study(connection, request.prior_study_id, principal)
        manifest = _sequence_manifest(connection, study_id)
        registry = connection.execute("SELECT COALESCE(MAX(updated_at),0) AS version FROM model_registry").fetchone()["version"]
        key = request.idempotency_key or hashlib.sha256(f"{study_id}:{request.profile}:{request.prior_study_id or ''}:{registry}:{QUALIFICATION_VERSION}".encode()).hexdigest()
        existing = connection.execute("SELECT * FROM analysis_jobs WHERE institution=? AND idempotency_key=?", (principal.institution, key)).fetchone()
        if existing:
            return _job_payload(existing)
        enabled = connection.execute("SELECT id,display_name,required_sequences_json FROM model_registry WHERE enabled=1 AND status='clinically_enabled'").fetchall()
        modules: list[dict[str, Any]] = []
        if "MR" not in str(study["modalities"]).split("\\"):
            state, message = "abstained", "This profile requires an MR study"
        elif not enabled:
            state, message = "abstained", "No clinically validated brain MRI module is enabled"
        else:
            for model in enabled:
                required = set(json.loads(model["required_sequences_json"]))
                missing = sorted(required - set(manifest["sequences"]))
                modules.append({"model_id": model["id"], "display_name": model["display_name"], "state": "eligible" if not missing else "skipped", "missing_sequences": missing})
            state = "queued" if any(module["state"] == "eligible" for module in modules) else "abstained"
            message = "Queued for the on-premises worker" if state == "queued" else "Required sequences are missing"
        job_id = uuid.uuid4().hex
        connection.execute("INSERT INTO analysis_jobs(id,institution,study_id,profile,prior_study_id,idempotency_key,state,manifest_json,modules_json,message,requested_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (job_id, principal.institution, study_id, request.profile, request.prior_study_id, key, state, json.dumps(manifest), json.dumps(modules), message, principal.user_id, now, now))
        job = connection.execute("SELECT * FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()
    _audit(principal, "analysis.request", "analysis_job", job_id, outcome="success" if state == "queued" else "abstained", details={"profile": request.profile})
    return _job_payload(job)


@router.get("/analysis-jobs/{job_id}")
def analysis_job(job_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        row = connection.execute("SELECT * FROM analysis_jobs WHERE id=? AND institution=?", (job_id, principal.institution)).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "analysis_job_not_found", "message": "Analysis job was not found"})
    return _job_payload(row)


@router.post("/analysis-jobs/{job_id}/cancel")
def cancel_analysis_job(job_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        row = connection.execute("SELECT * FROM analysis_jobs WHERE id=? AND institution=?", (job_id, principal.institution)).fetchone()
        if not row:
            raise HTTPException(404, detail={"code": "analysis_job_not_found", "message": "Analysis job was not found"})
        if row["state"] not in {"queued", "qualifying", "running"}:
            raise HTTPException(409, detail={"code": "analysis_not_cancellable", "message": "Only active analysis jobs can be cancelled"})
        connection.execute("UPDATE analysis_jobs SET state='cancelled',message=?,updated_at=? WHERE id=?", ("Cancelled by clinician", time.time(), job_id))
        row = connection.execute("SELECT * FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()
    _audit(principal, "analysis.cancel", "analysis_job", job_id)
    return _job_payload(row)


@router.get("/studies/{study_id}/analysis-results")
def analysis_results(study_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        rows = connection.execute("SELECT id,job_id,result_json,created_at FROM analysis_results WHERE study_id=? AND institution=? ORDER BY created_at DESC", (study_id, principal.institution)).fetchall()
        job = connection.execute("SELECT * FROM analysis_jobs WHERE study_id=? AND institution=? ORDER BY created_at DESC LIMIT 1", (study_id, principal.institution)).fetchone()
    return {"items": [{**json.loads(row["result_json"]), "id": row["id"], "job_id": row["job_id"], "created_at": row["created_at"]} for row in rows],
            "latest_job": _job_payload(job) if job else None}


@router.get("/studies/{study_id}/report-draft")
def get_report_draft(study_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        row = connection.execute("SELECT version,status,findings_text,impression_text,updated_by,updated_at FROM report_drafts WHERE study_id=? AND institution=?", (study_id, principal.institution)).fetchone()
    return dict(row) if row else {"version": 0, "status": "empty", "findings_text": "", "impression_text": "", "updated_by": None, "updated_at": None}


@router.put("/studies/{study_id}/report-draft")
def put_report_draft(study_id: str, update: ReportDraftUpdate, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    if principal.role not in {"radiologist", "administrator"}:
        raise HTTPException(403, detail={"code": "draft_forbidden", "message": "Only radiologists can edit report drafts"})
    now = time.time()
    with _db() as connection:
        _require_study(connection, study_id, principal)
        current = connection.execute("SELECT * FROM report_drafts WHERE study_id=? AND institution=?", (study_id, principal.institution)).fetchone()
        current_version = int(current["version"]) if current else 0
        if update.version != current_version:
            raise HTTPException(409, detail={"code": "draft_version_conflict", "message": "The draft changed; reload it before saving"})
        next_version = current_version + 1
        snapshot = {"version": next_version, "status": "draft", "findings_text": update.findings_text, "impression_text": update.impression_text,
                    "updated_by": principal.user_id, "updated_at": now}
        connection.execute("INSERT INTO report_drafts(study_id,institution,version,status,findings_text,impression_text,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(study_id,institution) DO UPDATE SET version=excluded.version,status=excluded.status,findings_text=excluded.findings_text,impression_text=excluded.impression_text,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                           (study_id, principal.institution, next_version, "draft", update.findings_text, update.impression_text, principal.user_id, now))
        connection.execute("INSERT INTO report_draft_history(id,study_id,institution,version,state_json,changed_by,changed_at) VALUES(?,?,?,?,?,?,?)",
                           (uuid.uuid4().hex, study_id, principal.institution, next_version, json.dumps(snapshot), principal.user_id, now))
    _audit(principal, "report_draft.update", "study", study_id, details={"version": next_version})
    return snapshot


@router.post("/studies/{study_id}/report-draft/review")
def review_report_draft(study_id: str, checklist: ReviewChecklist, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    if principal.role != "radiologist":
        raise HTTPException(403, detail={"code": "review_forbidden", "message": "A radiologist must review the draft"})
    if not all((checklist.patient_identity_confirmed, checklist.laterality_checked, checklist.priors_checked,
                checklist.critical_findings_checked, checklist.warnings_resolved)):
        raise HTTPException(422, detail={"code": "review_checklist_incomplete", "message": "Complete every safety check before review"})
    now = time.time()
    with _db() as connection:
        _require_study(connection, study_id, principal)
        current = connection.execute("SELECT * FROM report_drafts WHERE study_id=? AND institution=?", (study_id, principal.institution)).fetchone()
        if not current:
            raise HTTPException(409, detail={"code": "draft_missing", "message": "Save a draft before reviewing it"})
        if checklist.version != int(current["version"]):
            raise HTTPException(409, detail={"code": "draft_version_conflict", "message": "The draft changed; reload it before review"})
        connection.execute("UPDATE report_drafts SET status='reviewed',updated_by=?,updated_at=? WHERE study_id=? AND institution=?",
                           (principal.user_id, now, study_id, principal.institution))
        row = connection.execute("SELECT version,status,findings_text,impression_text,updated_by,updated_at FROM report_drafts WHERE study_id=? AND institution=?", (study_id, principal.institution)).fetchone()
    _audit(principal, "report_draft.review", "study", study_id, details={"version": checklist.version, "not_signed": True})
    return dict(row)


@router.get("/audit/recent")
def recent_audit(principal: Annotated[Principal, Depends(_principal)], limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    if principal.role != "administrator":
        raise HTTPException(403, detail={"code": "administrator_required", "message": "Administrator role required"})
    with _db() as connection:
        rows = connection.execute("SELECT timestamp,user_id,role,action,resource_type,resource_id,outcome FROM audit_events WHERE institution=? ORDER BY id DESC LIMIT ?", (principal.institution, limit)).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/reviewers")
def list_reviewers(principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    if principal.role != "administrator":
        raise HTTPException(403, detail={"code": "administrator_required", "message": "Administrator role required"})
    with _db() as connection:
        rows = connection.execute(
            "SELECT id,name,affiliation,expertise,source_url,status,created_at "
            "FROM reviewers WHERE institution=? ORDER BY created_at DESC,id DESC",
            (principal.institution,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/reviewers", status_code=201)
def add_reviewer(entry: ReviewerCreate, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    if principal.role != "administrator":
        raise HTTPException(403, detail={"code": "administrator_required", "message": "Administrator role required"})
    reviewer_id = str(uuid.uuid4())
    created_at = time.time()
    with _db() as connection:
        connection.execute(
            "INSERT INTO reviewers(id,institution,name,affiliation,expertise,source_url,status,added_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (reviewer_id, principal.institution, entry.name.strip(), entry.affiliation.strip(),
             entry.expertise.strip(), entry.source_url.strip(), "proposed", principal.user_id, created_at),
        )
    _audit(principal, "reviewer.propose", "reviewer", reviewer_id)
    return {"id": reviewer_id, **entry.model_dump(), "status": "proposed", "created_at": created_at}
