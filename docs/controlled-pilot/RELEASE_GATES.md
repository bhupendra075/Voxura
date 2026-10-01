# Release Gates and Stop Conditions

Each gate is PASS, FAIL, or NOT RUN. NOT RUN is a failure for release. Evidence paths and reviewers are recorded in `release-evidence.json`.

1. **Scope:** intended-use banner and supported-object policy are visible and unsupported features are disabled.
2. **Data integrity:** no silent instance loss, source mutation, duplicate ambiguity, or silent reinterpretation.
3. **Display:** pixel values, VOI behavior, ordering, orientation, and calibrated measurements match the approved reference within the documented tolerance.
4. **Identity:** no stale patient/study context and no cross-institution access.
5. **Security:** no development login, default secret, SQLite production database, critical/high unresolved vulnerability, authentication bypass, or PHI in logs.
6. **Reliability:** clean install, restart, bounded resource use, backup, restore, and rollback are demonstrated.
7. **Traceability:** fixtures, software artifacts, dependencies, tests, failures, reviewers, and hashes are reproducible.

## Automatic NO-GO

Wrong patient/study/series/frame, incorrect orientation or laterality, measurement outside tolerance, silent loss, source mutation, false-normal messaging, tenant escape, authentication bypass, PHI leakage, failed restore, non-reproducible migration, unresolved critical/high vulnerability, or a bypassable mandatory warning.

A NO-GO build may be used only as an internal demonstration with synthetic or de-identified data and the evaluation disclosure visible.
