# Voxura

This repository contains two separate applications:

- A versioned `/v2` CPU/OpenMP image-processing API for grayscale box blur and Sobel processing.
- A `/v3` DICOM evaluation viewer for immutable ingestion, institution-scoped worklists, reversible presentation state, proposed reviewer records, and reviewable draft notes.

The viewer is a development-stage **radiologist-assist tool**. It is not an autonomous diagnosis system, certified diagnostic workstation, or substitute for a qualified clinician. The current AI worker is `qualification-only` and abstains; no model is enabled for clinical findings.

**Release status: NO-GO.** The October 6 target is a controlled, single-site evaluation using licensed, de-identified data, not a clinical production release. All seven formal gates remain `NOT_RUN`. Approved reference data and tolerances, confirmed site reviewers, institutional identity, and an isolated operational rehearsal are still required. See the [release gates](docs/controlled-pilot/RELEASE_GATES.md), [supported DICOM matrix](docs/controlled-pilot/SUPPORTED_DICOM.md), and [project plan](docs/PROJECT_PLAN.md).

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

From the repository root, run `python ops/scripts/verify_release.py` for static release controls. It also checks the ignored `ops/.env` when present and fails on placeholder secrets. The [engineering CI workflow](.github/workflows/engineering.yml) repeats backend, native processor, frontend, and static checks; it has not yet run on a hosted runner.

The October 4 local run had **51 backend tests passed, 1 native-extension skip, and 1 dependency warning**; **19 frontend tests, typecheck, lint, and build passed**. Local release preflight failed because `ops/.env` has a placeholder or unset `POSTGRES_PASSWORD`. These engineering checks do not establish pilot acceptance.

### Production clinical configuration

Production startup fails unless the development session is disabled, PostgreSQL is configured and migrated, and a trusted identity-proxy secret is provided. JWT sessions are development/test-only.

```text
CLINICAL_ENV=production
CLINICAL_DEV_MODE=0
CLINICAL_AUTH_MODE=proxy
CLINICAL_TRUSTED_PROXY_SECRET=<at-least-32-byte-secret-manager-value>
CLINICAL_DATABASE_URL=postgresql://...
CLINICAL_DATA_ROOT=<encrypted-controlled-storage>
PACS_DICOMWEB_URL=https://...
PACS_BEARER_TOKEN=<secret-manager-value>
```

Production requires PostgreSQL at Alembic revision `20261004_002`, a disabled development session, and a trusted signed identity proxy. Apply production migrations only through the approved [deployment runbook](docs/controlled-pilot/DEPLOYMENT.md). The bundled Nginx clears browser identity headers and does not provide institutional login or signing; unmodified Compose cannot grant clinical access. Clinical records are institution-scoped, source objects are content-hashed, and analysis artifacts remain separate from source DICOM.

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
npm run build
```

Set `VITE_API_BASE_URL` when the API is not served from `http://localhost:8000`.
`VITE_CLINICAL_DEV_SESSION=true` is supplied only by `.env.development`; production builds must obtain an institution-issued session and never call `/v3/session/dev`.

The AI Assist panel displays study qualification, detected sequences, model-registry state, explicit abstention, editable findings/impression drafts, optimistic draft versions, and a mandatory radiologist review checklist. “No model findings” is never presented as a normal study.

Institution administrators can add proposed reviewers in the client. These records are institution-scoped nominations, not confirmed appointments or formal signoff.

### Optional Supabase Postgres

The backend can use a Supabase PostgreSQL endpoint through `SUPABASE_DATABASE_URL`; `CLINICAL_DATABASE_URL` takes precedence. Keep credentials in an ignored environment file or approved secret manager. No Supabase client key is needed in the browser for this backend connection. The same migration, identity, and pilot approval gates apply as for any other PostgreSQL deployment.

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
