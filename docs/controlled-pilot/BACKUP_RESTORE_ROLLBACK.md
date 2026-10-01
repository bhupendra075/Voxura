# Backup, Restore, Upgrade, and Rollback

## Backup

1. Quiesce imports and record the current release/image digest and schema version.
2. Run `ops/scripts/backup.ps1 -Destination <new-file.dump>` from the repository root.
3. Store the dump and generated SHA-256 file in encrypted, access-controlled storage separate from the host.
4. Back up the immutable clinical-object volume using the institution's block/object backup mechanism and record its snapshot identifier. The database dump alone is insufficient.
5. Test a restore on an isolated host before accepting the backup.

## Restore drill

1. Use an isolated evaluation environment with no real patient data and no external routes.
2. Restore the matching object-store snapshot first.
3. Run `ops/scripts/restore.ps1 -Backup <file.dump> -Confirmation RESTORE-DEIDENTIFIED-EVALUATION-DATABASE`.
4. Start the candidate release and confirm readiness, schema version, object hashes, study/series/instance counts, audit continuity, and smoke workflows.
5. Record recovery time, data-loss interval, discrepancies, reviewer, and result. Any discrepancy is a release failure.

## Upgrade

1. Produce and verify a fresh backup and object-store snapshot.
2. Build/load the new immutable images without replacing the previous images.
3. Review migration direction and downgrade limitations. The baseline migration is intentionally irreversible: rollback requires restoring the pre-migration PostgreSQL backup, not running `alembic downgrade`. Production schema changes require a named operator and approval.
4. Stop access, apply migration, start the candidate, and execute the full smoke checklist.
5. Reopen access only after an explicit GO.

## Rollback

Trigger rollback for a failed migration, failed readiness, identity/display integrity failure, audit failure, or any automatic NO-GO condition.

Do not attempt an in-place downgrade of the clinical baseline. Stop the API, preserve the failed database for investigation, restore the verified pre-migration backup into a clean database, deploy the previously recorded image digests, and run readiness plus the full smoke checklist before reopening access.

1. Stop web and API access; preserve logs and failed-state evidence.
2. Restore the previous database backup and matching object-store snapshot in a controlled maintenance window.
3. start the previously approved immutable image digests.
4. Run readiness, source-hash, count, tenant-boundary, and viewer smoke checks.
5. Record the incident and keep the failed release disabled. Never attempt to fix a failed production database manually while users retain access.
