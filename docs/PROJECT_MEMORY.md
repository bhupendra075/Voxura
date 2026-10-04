# Voxura project memory

## 4 October 2026 local engineering checkpoint

- Reviewer proposals are implemented in the institution-scoped API and client. A prepared Alembic revision requires an approved migration before production use; proposed contacts are not confirmed reviewers.
- The reviewer migration now uses Alembic's active connection, and a focused in-memory migration test verifies its table and index. The production schema check expects revision `20261004_002`.
- Current local checks: 51 backend tests passed, 1 native-extension skip, 1 dependency warning; 19 frontend tests passed; typecheck, lint, build, and `git diff --check` passed. A new CI workflow is prepared but has not run on a hosted runner.
- Local release preflight fails because `ops/.env` has a placeholder or unset database password. Formal Scope, Data integrity, Display, Identity, Security, Reliability, and Traceability gates remain NOT_RUN; release decision remains **NO-GO**.
- October 6 controlled-pilot target is at risk. Next work needs approved reference data and tolerances with confirmed site reviewers, the institution identity gateway, and an isolated rehearsal environment.

Last reviewed: **1 October 2026 (Asia/Calcutta)**. Code baseline: `49d7d3690feed96a5eb6a11a7b86e2d1a79a3cc9`. This file preserves project context; it does not replace current code, test output or release evidence.

## Purpose and decisions to preserve

- Voxura combines a separate `/v2` CPU/OpenMP grayscale processor with a `/v3` institution-scoped DICOM evaluation-viewer foundation. The README also uses the legacy MedScope name.
- October 6 is the existing controlled single-site evaluation target, conditional on release gates. It is not a production clinical launch.
- Preserve immutable source DICOM and hashes. Presentation, notes and analysis artifacts stay separate from source objects.
- Keep institution-scoped identity and authorization. Production requires PostgreSQL, migrations and trusted signed proxy identity; development JWT sessions are not production authentication.
- The bundled Nginx clears browser identity headers and does not implement OIDC/signing. Compose alone is infrastructure rehearsal until the institution gateway is integrated.
- Keep the narrow single-frame, uncompressed MR/CT allowlist. Unsupported objects must fail explicitly; spacing problems disable calibrated measurements where required.
- AI remains disabled/qualification-only, with explicit abstention. Absence of model findings must never imply a normal study. Research fixtures and results remain outside the clinical worklist.
- Draft notes/review APIs are implemented, but the pilot does not authorize clinical reports, diagnoses or automatic signing.
- Retain current architecture for the pilot; prioritize acceptance and operational evidence before expanding features.

## Version and history snapshot

- Backend package/API metadata: `2.0.0`; frontend: `0.0.1`, with scaffold name `@figma/my-make-file`.
- `/v2` and `/v3` are API namespaces, not product release versions. No Git release tags were found.
- July 9: initial project/setup. September 29: processor improvements and clinical-viewer foundation. October 1: controlled-pilot workflow and deterministic synthetic CT fixture.
- Proposed future product versions in [PROJECT_PLAN.md](PROJECT_PLAN.md): `0.1.0-rc.1`, accepted pilot `0.1.0`, then scoped expansion `0.2.0`. None has been released by this planning task.

## Latest recorded evidence

Source: ignored root `checkpoint-20261001.yaml`, dated October 1, 2026.

- Backend: 48 passed; 1 native-extension skip; 1 dependency deprecation warning.
- Frontend: prior recorded 18 tests, typecheck and build passed; latest fixture change did not touch frontend. Lint pass is not recorded in that checkpoint.
- Static release preflight: passed for 9 required documents/controls. This does not validate the seven formal release gates or actual recovery/security behavior.
- Synthetic technical CT reference: three deterministic instances; source hash/pixel preservation, reverse-upload geometry ordering, calibration and byte equality covered by integration test.
- Repeated synthetic manifest SHA-256: `9204b275ec20c50e471b99e7ccb6c01a532edcf2168ba348835e51fe69015f3b`.
- Formal reference/tolerances and reviewer signoff were unavailable. Current release status: **NO-GO**; formal gates remain NOT RUN.

These are historical recorded results. The planning task inspected code and documents and did not rerun application tests or deploy services.

## Resume with these next three tasks

1. Obtain approved licensed de-identified fixture provenance, reference images, reviewer and tolerances; run formal scope/data-integrity/display/identity acceptance.
2. Integrate institutional identity and run security/reliability acceptance in an isolated pilot-like environment, including dependency/log review, clean installation, load, backup/restore and rollback.
3. Assemble actual `release-evidence.json` with all seven gate results, reviewers, artifact hashes and explicit GO/NO-GO; do not convert missing evidence into PASS.

Engineering checks, owner assignment and product-version cleanup can progress while site approvals are pending. Dates and detailed backlog are in [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Known gaps and dependencies

- Approved reference fixtures/tolerances and named reviewers are external dependencies.
- Institutional OIDC gateway/TLS and pilot host configuration are not proven by repository code.
- Production PostgreSQL migration, restore/rollback, actual vulnerability status, browser acceptance and site PACS interoperability still need environment-specific evidence.
- Native accelerated path was skipped in the saved backend run; Compose currently permits fallback processing.
- Synthetic CT checks do not establish real-reference display parity, MR coverage or clinical readiness.
- Future compressed/enhanced objects, research model activation and production clinical scope require separate work and acceptance.

## Updating and resuming

At the next work window, inspect the newest ignored checkpoint, current Git status/history, relevant running services and actual evidence before changing code. Do not assume historical clean-tree/service observations still apply.

After work, write a fresh ignored checkpoint following [the checkpoint contract](controlled-pilot/CHECKPOINT.md). Record completed acceptance criteria, exact verification outcomes/skips, failures, service state, next three tasks and blockers. Keep secrets, PHI and source patient data out of memory and checkpoints.

Update this memory for durable scope/architecture decisions and accepted milestones; update the plan for priorities/dates. Preserve failed or missing gate evidence and known limitations. External deployment, real patient data, license acceptance, production migration and destructive operations require their applicable authorization; preparing this plan does not authorize them.
