# MedScope Viewer and High-Performance Image Processor

This repository contains two deliberately separated applications:

- A versioned `/v2` CPU/OpenMP image-processing API for grayscale box blur and Sobel processing.
- A `/v3` clinical-viewer foundation for immutable DICOM ingestion, institution-scoped worklists, reversible presentation state, and evidence-grounded brain-MRI assistance.

The clinical surface is a development-stage **radiologist-assist tool**. It is not an autonomous diagnosis system, certified diagnostic workstation, or substitute for a qualified clinician. No model is enabled merely because it is listed in the registry.

## Backend

Use Python 3.10+ and, for the native image processor, a C++17 compiler with OpenMP.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[opencv,test]"
.\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Run verification with:

```powershell
cd backend
.\.venv\Scripts\python -m pytest
```

### Production clinical configuration

Production startup fails unless the development session is disabled, a non-default JWT secret is provided, and PostgreSQL is configured.

```text
CLINICAL_ENV=production
CLINICAL_DEV_MODE=0
CLINICAL_JWT_SECRET=<secret-manager-value>
CLINICAL_DATABASE_URL=postgresql://...
CLINICAL_DATA_ROOT=<encrypted-controlled-storage>
PACS_DICOMWEB_URL=https://...
PACS_BEARER_TOKEN=<secret-manager-value>
```

Clinical records are institution-scoped from the authenticated token. Browser responses for source frames use `private, no-store`, source objects are content-hashed, and analysis artifacts remain separate from source DICOM.

The current AI worker reports `qualification-only`. It checks modality and available sequences, then explicitly abstains because no validated module is enabled. AutoRG-Brain and MONAI entries are research candidates; AI-Rad Companion Brain MR is a commercial candidate that may only be used within its licensed, jurisdiction-approved intended use.

### Brain-MRI assist APIs

- `GET /v3/ai/capabilities`
- `POST /v3/studies/{studyId}/analysis-jobs`
- `GET /v3/analysis-jobs/{jobId}`
- `POST /v3/analysis-jobs/{jobId}/cancel`
- `GET /v3/studies/{studyId}/analysis-results`
- `GET/PUT /v3/studies/{studyId}/report-draft`
- `POST /v3/studies/{studyId}/report-draft/review`

There is intentionally no generic diagnosis endpoint and no automatic report-signing route.

### Reviewing old development fixtures

Tests now use an isolated temporary database. To inspect fixtures created by older test runs:

```powershell
cd backend
.\.venv\Scripts\python tools\cleanup_training_fixtures.py
```

The command is a dry run. Re-run with `--apply` only after reviewing every listed study ID.

## Frontend

```powershell
cd frontend
npm ci
npm run dev
npm run typecheck
npm run lint
npm test
```

Set `VITE_API_BASE_URL` when the API is not served from `http://localhost:8000`.

The AI Assist panel displays study qualification, detected sequences, model-registry state, explicit abstention, editable findings/impression drafts, optimistic draft versions, and a mandatory radiologist review checklist. “No model findings” is never presented as a normal study.

## Image-processing API

The preferred `/v2` backend is the pybind11/OpenMP extension; OpenCV and NumPy are development fallbacks. Set `PROCESSOR_REQUIRE_NATIVE=1` in production to fail instead of silently falling back.

- `POST /v2/process`
- `GET /v2/capabilities`
- Deprecated compatibility route: `POST /process`

Resource and concurrency controls include `PROCESSOR_MAX_UPLOAD_BYTES`, `PROCESSOR_MAX_DIMENSION`, `PROCESSOR_MAX_MEGAPIXELS`, `PROCESSOR_MAX_KERNEL_SIZE`, `PROCESSOR_MAX_CONCURRENCY`, and `OMP_NUM_THREADS`.

## Benchmarks

```powershell
cd backend
.\.venv\Scripts\python benchmarks\run.py
```

The benchmark prints deterministic JSON and does not modify repository files unless `--output` is explicitly supplied. Public MRI datasets and model weights must not be downloaded or used commercially until their licenses and institutional governance have been reviewed.
