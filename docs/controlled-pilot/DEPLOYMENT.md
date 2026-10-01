# Controlled-Pilot Deployment Runbook

> **Current integration gate:** the bundled Nginx intentionally removes all
> browser-supplied identity headers and does not implement OIDC or header
> signing. Consequently, the unmodified Compose bundle is expected to return
> `401 trusted_identity_required` for clinical APIs. It is suitable for
> infrastructure rehearsal only until an institution-approved identity gateway
> is placed at the API trust boundary and the integration is verified. Do not
> weaken this control by forwarding unsigned browser headers.

## Preconditions

- Dedicated on-premises host with Docker Engine and Compose v2; no public inbound route.
- Encrypted host volume and encrypted, access-controlled backup destination.
- Licensed, de-identified fixtures only; completed provenance manifests stored outside the clinical object root.
- Institution-approved reverse proxy/TLS and identity configuration. The sample bind address is loopback and must not be changed before that review.
- The identity gateway must authenticate with institutional OIDC, map a stable user id, approved role, and institution, then HMAC-sign the five `X-Voxura-*` headers. The bundled Nginx deliberately clears browser-supplied identity headers and is not an identity provider.
- Release artifact hashes, SBOM, vulnerability report, test report, known issues, and named operator/reviewer.

## Prepare

1. Verify the release tag/commit and artifact checksums on the offline host.
2. Copy `ops/.env.example` to `ops/.env`, replace every placeholder from the approved secret manager, and restrict file permissions. Generate the PostgreSQL password from URL-safe characters because it is embedded in the connection URI; preflight rejects URI-reserved characters.
3. Run `python ops/scripts/verify_release.py`. A failure is a NO-GO.
4. Render and review configuration with `docker compose --env-file ops/.env -f ops/compose.yaml config`; confirm no secrets are printed into retained logs.
5. Build or load the pinned images and record their immutable image digests.
6. Verify the approved identity gateway can generate the five signed
   `X-Voxura-*` headers without exposing the signing secret to the browser or
   bundled web container. Without this integration, stop at infrastructure
   rehearsal and record NO-GO for user access.

## Start and verify

1. Start services with `docker compose --env-file ops/.env -f ops/compose.yaml up -d`. The one-shot `migrate` service must complete before the API starts; never run migrations from API startup.
2. Wait for every service to become healthy. `/health` proves the API process is alive; `/ready` must verify required storage and database dependencies.
3. Confirm the evaluation-only banner, authenticated session, institution boundary, empty initial worklist, and disabled AI state.
4. Import the approved smoke fixture. Verify instance counts, rejection warnings, source hashes, slice order, patient banner, window/level, and logout state clearing.
5. Record operator, time, Git commit, image digests, database schema version, test output, and GO/NO-GO decision.

## Operational limits

- Do not expose PostgreSQL or the API directly to other networks.
- Do not enable a development session, default secret, SQLite, PACS token, or model at runtime.
- Stop import when storage or memory alarms fire. Never delete source objects to recover space during an active evaluation.
- Treat loss of readiness, identity mismatch, incomplete-stack concealment, or audit failure as an immediate stop condition.

## Shutdown

Use `docker compose --env-file ops/.env -f ops/compose.yaml stop`. Do not use volume-removal commands. Record the stop event and retain audit, object, backup, and release evidence according to the approved retention policy.
