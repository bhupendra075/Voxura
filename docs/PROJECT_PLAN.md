# Voxura project plan

As of **4 October 2026 (Asia/Calcutta)**. Baseline: `49d7d3690feed96a5eb6a11a7b86e2d1a79a3cc9`; current release work is uncommitted.

## Goal and current position

Build a reliable, institution-scoped DICOM evaluation viewer, while retaining a separate high-performance grayscale image-processing API. The existing October 6 target is a supervised, single-site, on-premises evaluation using licensed, de-identified data. It is not a clinical production launch.

**Current status: development foundation implemented; release NO-GO.** Formal acceptance, institutional identity integration, and operational evidence are outstanding. The schedule below is proposed; dates do not override acceptance gates.

Latest local engineering run: 51 backend tests passed with 1 native skip; 19 frontend tests, typecheck, lint, and build passed. The prepared reviewer migration has an isolated database test. Engineering CI is defined but has not run remotely. Static release preflight fails on the placeholder database password in the local `ops/.env`; all seven formal gates remain NOT_RUN. October 6 is at risk pending site approvals, identity integration, and an isolated rehearsal.

## Tech stack already in the repository

| Layer | Current technology | Purpose |
|---|---|---|
| Web application | React 18.3.1, TypeScript 5.9.2, Vite 6.4.3 | Typed worklist and viewer application |
| Imaging | Cornerstone core, tools and DICOM loader 4.12.6 | DICOM rendering and interaction |
| UI | Tailwind CSS 4.1.12, Radix/shadcn-style components, MUI 7.3.5, Lucide | Controls, layout and visual components |
| API | Python >=3.10, FastAPI 0.116.1, Uvicorn 0.35.0 | `/v2` processing and `/v3` viewer services |
| DICOM and pixels | pydicom 3.0.1, NumPy 2.2.6, Pillow 11.3.0 | Object validation, metadata and pixel handling |
| Native processing | C++17, OpenMP, pybind11, CMake/scikit-build-core | Box blur and Sobel acceleration |
| Processing fallbacks | OpenCV 4.12.0.88 or NumPy | Development processing when native extension is unavailable |
| Data | PostgreSQL 16.4 in Compose, psycopg 3.2.10; SQLite for development/test | Institution-scoped records and audit data |
| Schema management | Alembic 1.16.5, SQLAlchemy 2.0.43 | Database migration tooling |
| Identity | Trusted proxy with signed institution/user/role headers; PyJWT for development/test | Access control and institution isolation |
| Deployment | Docker Compose, Nginx, PowerShell backup/restore scripts | On-premises service and recovery foundation |
| Verification | pytest 8.4.2, Vitest 3.2.7, ESLint, TypeScript checks, release preflight | Automated engineering checks |

Retain this stack for the pilot. Prioritize verification and integration over framework changes. No AI model is enabled; the current worker is `qualification-only` and explicitly abstains. Institutional OIDC gateway integration is required, but is not supplied by the bundled Nginx.

## Version strategy

| Item | Observed version/status |
|---|---|
| Backend package and FastAPI metadata | `2.0.0` |
| Frontend package | `0.0.1`; package name remains `@figma/my-make-file` |
| API namespaces | `/v2` processor; `/v3` clinical-viewer foundation |
| Release tags | None found during this review |
| Database baseline migration | `20260930_001_clinical_baseline.py` |

API route versions are compatibility boundaries, not proof of product maturity. Adopt a separate Voxura product version: proposed `0.1.0-rc.1` after an evidence-complete candidate is assembled, `0.1.0` after controlled-pilot acceptance, and `0.2.0` for a later validated expansion. These are proposals, not existing releases. Reserve `1.0.0` for an explicitly defined production scope with its own acceptance and institutional requirements.

Before tagging, align product naming and version metadata, record the commit, schema revision, dependency lockfiles and image digests, and publish release notes with known limitations. Do not rename API routes solely to align package versions.

## Checkpoints reached

“Implemented” means present in code. “Recorded pass” means documented in the saved checkpoint; this planning review did not rerun those tests. Neither means formal release approval.

| Checkpoint | Evidence | Status and remaining boundary |
|---|---|---|
| Initial project and setup | July 9 commits `4be84ea4`, `2bff81c8` | Recorded history |
| Processor improvements | September 29 commits `ab6781a7`, `2b52ae53`; `/v2` routes and native sources | Implemented; native verification incomplete in latest saved run |
| Clinical-viewer foundation | September 29 commit `91a390e0`; clinical API and Cornerstone viewport | Implemented; formal display/identity acceptance outstanding |
| Controlled-pilot workflow | October 1 commits `7f0b6e09`, `c88dabf5`; pilot docs and ops assets | Implemented; site integration and rehearsal outstanding |
| Synthetic CT technical reference | October 1 commit `49d7d369`; fixture builder and integration test | Deterministic source hashes, pixel checks, geometry order and calibration recorded; not an approved clinical reference |
| Backend verification | `checkpoint-20261001.yaml` | Recorded: 48 passed, 1 native-extension skip, 1 dependency deprecation warning |
| Frontend verification | Previous results summarized in the same checkpoint | Recorded: 18 tests, typecheck and build passed; latest fixture commit did not change frontend; no lint pass recorded there |
| Release preflight | Same checkpoint; `ops/scripts/verify_release.py` | Recorded pass for 9 required documents and static controls; does not certify the seven release gates |

Implemented capabilities include immutable source storage with SHA-256 lineage, import rejection policies, institution-scoped worklists, viewer manifests, geometry and spacing warnings, reversible versioned presentation state, append-only audit controls, development/production authentication boundaries, analysis qualification and abstention, and reviewable draft-note APIs.

PACS query/metadata integration exists in code but site interoperability is unverified. Draft/report-related interfaces do not authorize clinical reporting or signing. The pilot supports validated single-frame MR/CT with uncompressed explicit/implicit VR little-endian pixels; compressed, enhanced and multi-frame objects remain unsupported.

## Development roadmap and future checkpoints

Owners below are proposed roles. Assign named people before treating the dates as commitments.

| Checkpoint | Proposed window | Work and deliverables | Acceptance / owner |
|---|---|---|---|
| C1: Reproducible engineering baseline | Oct 1–2 | Verify clean installation; run backend suite, frontend tests/typecheck/lint/build and release preflight; record versions and skipped checks; build/test native processor if included | Reproducible reports tied to a commit; native skip resolved or processor limitation explicitly scoped. Engineering lead |
| C2: Approved reference and viewer acceptance | Oct 2–3 | Obtain fixture provenance, approved reference images, tolerances and reviewer; compare pixels, VOI, rescale, ordering, orientation, calibrated measurements; test rejects, duplicates, corrupt objects, gaps and context switches | Documented Scope, Data integrity, Display and Identity results with evidence and reviewer. Engineering + site evaluator/data custodian |
| C3: Pilot identity and security integration | Oct 2–4, alongside C2 | Integrate institution-approved OIDC gateway at API trust boundary; verify signatures, expiry, logout, role and tenant denial; inspect logs/caches; inventory dependencies and scan built artifacts | Signed authenticated access works; unsigned/tampered/stale identities fail; no unresolved critical/high vulnerabilities or data leakage. Identity/security owner |
| C4: Operational rehearsal | Oct 4–5, after identity integration | Rehearse PostgreSQL migration on isolated host, readiness/restart, bounded load and storage limits; back up database and objects, restore and verify hashes; rehearse rollback | Clean install, recovery and rollback evidenced; resource thresholds documented. Operations owner |
| C5: Release decision | Oct 5–6, conditional | Assemble `release-evidence.json`, provenance, reports, SBOM, artifact digests, known issues, operator/reviewer names and release notes | All seven mandatory gates evidenced PASS before GO; otherwise defer pilot. Release owner + site reviewer |
| C6: Controlled pilot and feedback | Oct 6 target, only after C5 GO | Supervised evaluation under intended use; log usability/completeness issues and incidents; collect reviewer feedback | Site acceptance record; stop conditions respected; prioritized defect backlog. Site evaluator |
| C7: Stabilization | First 1–2 weeks after accepted pilot | Resolve pilot defects; add regression coverage for real failures; automate repeatable checks and artifact evidence; improve alerts/runbooks and documentation | Repeatable accepted build, no unresolved release-blocking defect. Engineering + operations |
| C8: Deliberate expansion | After stabilization; estimate after requirements | Evaluate PACS interoperability, broader DICOM support, larger-study performance and separately governed research AI | Each new capability gets scope, reference fixtures, tests and acceptance before enablement. Product + engineering + reviewers |

The critical path is approved references + institutional identity → formal viewer/security acceptance → recovery rehearsal → complete evidence → release decision. If reference approval or identity integration misses its window, October 6 remains a synthetic/de-identified internal demonstration with NO-GO disclosure; the pilot date moves.

## Prioritized remaining work

### P0 — Required before pilot GO

1. Assign the site evaluator, data custodian, identity/security owner, operations owner and release reviewer.
2. Obtain licensed de-identified MR/CT fixtures, provenance, approved reference outputs and explicit tolerances. The three-instance synthetic CT case cannot establish MR coverage or clinical display parity.
3. Run formal viewer acceptance, including browser navigation/logout context clearing, orientation/laterality, VOI/rescale and known-distance measurements.
4. Complete institutional identity gateway integration. Unmodified Compose intentionally returns `401 trusted_identity_required` for clinical APIs.
5. Run adversarial authentication/tenant checks and security review against the actual pilot configuration; produce dependency inventory/SBOM and vulnerability evidence.
6. Rehearse migration, restart, bounded load, backup, restore and rollback on an isolated pilot-like environment; verify restored objects and records.
7. Assemble actual release evidence with all seven gate results, failures, reviewers, hashes and explicit GO/NO-GO. Static preflight success alone is insufficient.

### P1 — Engineering readiness and maintainability

1. Resolve native-extension verification if promising accelerated `/v2` processing. Compose currently sets `PROCESSOR_REQUIRE_NATIVE=0`; document scope or enforce/test native requirements for that release.
2. Establish product naming/versioning and release notes; retain API compatibility and schema traceability.
3. Add automated CI checks for backend, frontend, native builds and static release checks. No tracked CI workflow was found in this review.
4. Add end-to-end browser coverage for import → worklist → viewer → presentation → logout, especially failure and identity-switch paths.
5. Record deployment performance budgets and operational alerts based on measurements rather than invented thresholds.
6. Review dependency/UI footprint and split large clinical modules when pilot feedback identifies maintenance problems.

### P2 — Future scope requiring separate acceptance

1. Validate PACS/DICOMweb interoperability against the intended institution; define exactly which retrieval workflows are supported.
2. Consider compressed/enhanced/multi-frame support only with a decoder strategy, fixtures and an expanded acceptance matrix.
3. Assess larger-study interaction and import throughput before adding infrastructure such as job queues or external object storage.
4. Evaluate AI candidates offline with approved licenses, pinned model hashes, representative data, preprocessing lineage and reviewer-approved metrics. Keep research output outside the clinical worklist.
5. Define any future clinical reporting/production scope separately; draft-note APIs and model registry entries do not establish that scope.

## Release decision and project memory

Formal gates are Scope, Data integrity, Display, Identity, Security, Reliability and Traceability. The latest checkpoint leaves formal gates NOT RUN; release status stays NO-GO until every mandatory gate has evidenced PASS. Preserve the existing [release gates](controlled-pilot/RELEASE_GATES.md), [supported matrix](controlled-pilot/SUPPORTED_DICOM.md), [risk register](controlled-pilot/RISK_REGISTER.md) and [deployment runbook](controlled-pilot/DEPLOYMENT.md) as the detailed contracts.

Use [PROJECT_MEMORY.md](PROJECT_MEMORY.md) for durable decisions and resume context. Continue the existing ignored `checkpoint*.yaml` convention for each work window, using the [checkpoint contract](controlled-pilot/CHECKPOINT.md). Update this roadmap when scope, dates or accepted checkpoints change. Store runtime evidence outside source control and keep secrets and patient data out of planning documents.
