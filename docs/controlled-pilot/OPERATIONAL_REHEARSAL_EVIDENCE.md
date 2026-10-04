# Operational rehearsal evidence record

This record defines the evidence required for the October 2026 controlled pilot. It is a checklist for a named operations owner on an isolated pilot-like host with licensed, de-identified fixtures. A completed checklist is not itself a PASS: attach the command outputs, hashes, timings, configuration review, and reviewer decision to the runtime `release-evidence.json`.

Current state on 4 October 2026: **NOT RUN / NO-GO**. The local preflight command `.\venv-test\Scripts\python.exe ops/scripts/verify_release.py` failed because `ops/.env` has an unset or placeholder `POSTGRES_PASSWORD`. No Docker executable was found in the prior checkpoint, and no isolated pilot-like host, institution-approved identity gateway, or named operations reviewer is recorded. Do not copy local placeholder values into an evidence bundle.

| Step | Evidence to retain | Pass condition | Current result |
| --- | --- | --- | --- |
| Host and configuration | Operator, isolated host identifier, no external route, OS/Compose versions, redacted rendered configuration, secret-manager attestation | Approved host and secret configuration; no development login, default secret, SQLite, or direct public database/API route | NOT RUN |
| Artifact traceability | Git commit and dirty-tree status, immutable image digests, dependency inventory/SBOM, vulnerability report, schema revision | Exact candidate reproducible; no unresolved critical/high finding | NOT RUN |
| Clean install and migration | Timestamped Compose events, migration output, schema revision, health and readiness outputs | One-shot migration completes before API, dependencies ready, no undocumented manual fix | NOT RUN |
| Identity and tenant boundary | Approved gateway configuration review, signed header positive case, unsigned/tampered/expired case, logout/session revocation, two institution identities and denied cross-tenant requests | Institution owner verifies actual pilot gateway and host isolation; no tenant escape or stale session | NOT RUN |
| Bounded load | Approved study/concurrency and storage budgets, request timings, CPU/memory/disk telemetry, error and warning logs | Limits remain inside documented budget without silent loss or exhausted resources | NOT RUN |
| Backup and restore | Database dump hash, matching immutable-object snapshot ID, isolated restore logs, restored object hashes, study/series/instance counts, audit continuity, recovery time and data-loss interval | Restored state exactly matches approved reference and documented recovery targets | NOT RUN |
| Rollback | Pre-migration backup and prior image digests, failed-state preservation, clean restore and smoke outputs | Prior candidate restored without in-place baseline downgrade; readiness, hashes, counts, tenant boundary and viewer smoke checks pass | NOT RUN |
| Log and cache review | Redacted application/proxy/audit logs and response headers from exercised paths | No patient data leakage, no secret leakage, no cacheable source frames | NOT RUN |

Local synthetic tests can establish a technical invariant but cannot establish gateway logout, reviewer identity, institutional tenant isolation, or approved clinical reference parity. Record those as NOT RUN until the actual site configuration and named reviewers are available. Any failed restore, tenant escape, identity bypass, incorrect clinical display, or other automatic NO-GO condition remains a release blocker.



