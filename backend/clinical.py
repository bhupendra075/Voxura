from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import jwt
import numpy as np
import pydicom
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pydicom.pixels import apply_modality_lut, apply_voi_lut
from PIL import Image

DATA_ROOT = Path(os.getenv("CLINICAL_DATA_ROOT", Path(__file__).with_name("clinical_data")))
DB_PATH = DATA_ROOT / "clinical.db"
OBJECT_ROOT = DATA_ROOT / "objects"
DATABASE_URL = os.getenv("CLINICAL_DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")
CLINICAL_ENV = os.getenv("CLINICAL_ENV", "development").lower()
JWT_SECRET = os.getenv("CLINICAL_JWT_SECRET", "development-only-change-me")
DEV_MODE = os.getenv("CLINICAL_DEV_MODE", "1" if CLINICAL_ENV == "development" else "0").lower() in {"1", "true", "yes"}
PACS_BASE_URL = os.getenv("PACS_DICOMWEB_URL", "").rstrip("/")
PACS_TOKEN = os.getenv("PACS_BEARER_TOKEN", "")
MAX_DICOM_BYTES = int(os.getenv("CLINICAL_MAX_DICOM_BYTES", str(512 * 1024 * 1024)))
SUPPORTED_MODALITIES = {"CR", "DX", "CT", "MR"}
ROLES = {"radiologist", "clinician", "technician", "administrator"}

if CLINICAL_ENV == "production":
    if JWT_SECRET == "development-only-change-me":
        raise RuntimeError("CLINICAL_JWT_SECRET must be configured in production")
    if DEV_MODE:
        raise RuntimeError("CLINICAL_DEV_MODE must be disabled in production")
    if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Production clinical storage requires PostgreSQL via CLINICAL_DATABASE_URL")

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
            study_id TEXT NOT NULL, user_id TEXT NOT NULL, state_json TEXT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL, PRIMARY KEY(study_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS reports (
            study_id TEXT PRIMARY KEY, status TEXT NOT NULL, text TEXT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
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
        CREATE TABLE IF NOT EXISTS audit_events (
            id {audit_id}, timestamp DOUBLE PRECISION NOT NULL, institution TEXT NOT NULL,
            user_id TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL,
            resource_type TEXT NOT NULL, resource_id TEXT, outcome TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        """)
        _add_column_if_missing(connection, "studies", "institution", "TEXT NOT NULL DEFAULT 'DEMO'")
        _add_column_if_missing(connection, "audit_events", "institution", "TEXT NOT NULL DEFAULT 'DEMO'")
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


class Principal(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    role: str
    institution: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")


class PresentationState(BaseModel):
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
    annotations: list[dict[str, Any]] = Field(default_factory=list)


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


def _principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
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


def _require_study(connection: _Database, study_id: str, principal: Principal):
    study = connection.execute("SELECT * FROM studies WHERE id=? AND institution=?", (study_id, principal.institution)).fetchone()
    if not study:
        raise HTTPException(404, detail={"code": "study_not_found", "message": "Study was not found"})
    return study


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
    if not DEV_MODE:
        raise HTTPException(404, detail="Not found")
    now = int(time.time())
    token = jwt.encode({"sub": "demo-radiologist", "role": "radiologist", "institution": "DEMO",
                        "aud": "clinical-viewer", "iat": now, "exp": now + 8 * 60 * 60}, JWT_SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": 8 * 60 * 60,
            "user": {"id": "demo-radiologist", "display_name": "Demo Radiologist", "role": "radiologist"}}


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


@router.post("/import", status_code=201)
async def import_dicom(files: list[UploadFile] = File(...), principal: Principal = Depends(_principal)) -> dict[str, Any]:
    if principal.role not in {"radiologist", "technician", "administrator"}:
        raise HTTPException(403, detail={"code": "import_forbidden", "message": "Your role cannot import studies"})
    accepted, rejected = [], []
    for upload in files:
        try:
            raw = await upload.read(MAX_DICOM_BYTES + 1)
            if len(raw) > MAX_DICOM_BYTES:
                raise ValueError("File exceeds the configured DICOM size limit")
            dataset = pydicom.dcmread(io.BytesIO(raw), force=False, stop_before_pixels=False)
            modality = _text(dataset, "Modality").upper()
            if modality not in SUPPORTED_MODALITIES:
                raise ValueError(f"Unsupported modality {modality or 'unknown'}")
            for field in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID"):
                if not getattr(dataset, field, None):
                    raise ValueError(f"Missing required {field}")
            if "PixelData" not in dataset:
                raise ValueError("DICOM object has no pixel data")
            digest = hashlib.sha256(raw).hexdigest()
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
                existing = connection.execute("SELECT id FROM instances WHERE sop_uid=? AND series_id=?", (sop_uid, series_id)).fetchone()
                instance_id = existing["id"] if existing else uuid.uuid4().hex
                if not existing:
                    object_path = OBJECT_ROOT / principal.institution / study_id / f"{instance_id}.dcm"
                    object_path.parent.mkdir(parents=True, exist_ok=True)
                    with object_path.open("xb") as target:
                        target.write(raw)
                    transfer_syntax = str(getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", ""))
                    connection.execute(
                        "INSERT INTO instances(id,series_id,sop_uid,instance_number,frame_count,transfer_syntax,object_path,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (instance_id, series_id, sop_uid, _integer(dataset, "InstanceNumber"), int(getattr(dataset, "NumberOfFrames", 1)),
                         transfer_syntax, str(object_path), digest, now),
                    )
            accepted.append({"filename": upload.filename, "study_id": study_id, "series_id": series_id, "instance_id": instance_id})
        except Exception as exc:
            rejected.append({"filename": upload.filename, "reason": str(exc)[:240]})
    _audit(principal, "dicom.import", "study", details={"accepted": len(accepted), "rejected": len(rejected)})
    return {"accepted": accepted, "rejected": rejected}


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


@router.get("/instances/{instance_id}/dicom")
def raw_instance(instance_id: str, principal: Annotated[Principal, Depends(_principal)]) -> Response:
    path = _instance_path(instance_id, principal)
    _audit(principal, "instance.retrieve", "instance", instance_id)
    return Response(path.read_bytes(), media_type="application/dicom", headers={"Cache-Control": "private, no-store"})


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
        row = connection.execute("SELECT state_json FROM presentation_states WHERE study_id=? AND user_id=?", (study_id, principal.user_id)).fetchone()
    return PresentationState.model_validate_json(row["state_json"]) if row else PresentationState()


@router.put("/studies/{study_id}/presentation-state")
def put_presentation_state(study_id: str, state: PresentationState, principal: Annotated[Principal, Depends(_principal)]) -> PresentationState:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        connection.execute("INSERT INTO presentation_states(study_id,user_id,state_json,updated_at) VALUES(?,?,?,?) ON CONFLICT(study_id,user_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at", (study_id, principal.user_id, state.model_dump_json(), time.time()))
    _audit(principal, "presentation.update", "study", study_id)
    return state


@router.get("/studies/{study_id}/report")
def study_report(study_id: str, principal: Annotated[Principal, Depends(_principal)]) -> dict[str, Any]:
    with _db() as connection:
        _require_study(connection, study_id, principal)
        row = connection.execute("SELECT status,text,updated_at FROM reports WHERE study_id=?", (study_id,)).fetchone()
    return dict(row) if row else {"status": "unavailable", "text": "No signed report is available for this study.", "updated_at": None}


def _sequence_manifest(connection: _Database, study_id: str) -> dict[str, Any]:
    rows = connection.execute("SELECT id,modality,description,rows,columns FROM series WHERE study_id=? ORDER BY series_number", (study_id,)).fetchall()
    detected: set[str] = set()
    for row in rows:
        text = f"{row['modality']} {row['description'] or ''}".upper().replace("-", "")
        aliases_by_name = {"T1C": ("T1C", "T1 POST", "T1+", "MPRAGE+C"), "FLAIR": ("FLAIR",), "DWI": ("DWI", "DIFF"), "ADC": ("ADC",), "SWI": ("SWI", "SUSCEPT"), "T2": ("T2",), "T1": ("T1", "MPRAGE")}
        for name, aliases in aliases_by_name.items():
            if any(alias in text for alias in aliases):
                detected.add(name)
    return {"series_count": len(rows), "sequences": sorted(detected),
            "series": [{"id": row["id"], "description": row["description"], "rows": row["rows"], "columns": row["columns"]} for row in rows],
            "warnings": ["Sequence classification is metadata-derived and requires radiologist confirmation"]}


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
        key = request.idempotency_key or hashlib.sha256(f"{study_id}:{request.profile}:{request.prior_study_id or ''}:{registry}".encode()).hexdigest()
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
