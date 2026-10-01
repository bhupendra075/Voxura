# Controlled-Pilot Risk Register

| ID | Hazard | Control | Verification | Release impact |
|---|---|---|---|---|
| R-01 | Wrong patient or stale study displayed | Persistent identity banner; clear viewport state on navigation/logout | Browser identity-switch test | NO-GO |
| R-02 | Missing or incorrectly ordered slices | Geometry ordering, duplicate/gap warnings, manifest counts | Reference-stack comparison | NO-GO |
| R-03 | Incorrect grayscale presentation | Preserve pixel metadata, rescale and VOI; reference parity | Pixel/VOI comparison | NO-GO |
| R-04 | Invalid measurement | Require consistent pixel spacing and calibrated tool | Known-distance fixture | Disable tool or NO-GO |
| R-05 | Source object mutation | Immutable object store, SHA-256 lineage | Re-hash after workflows | NO-GO |
| R-06 | Unsupported object appears usable | Positive allowlist and explicit rejection | Negative fixture corpus | NO-GO |
| R-07 | Cross-tenant disclosure | Institution-scoped queries and authorization | Adversarial tenant tests | NO-GO |
| R-08 | PHI disclosure in logs/cache | De-identified pilot data, redaction, `no-store` | Log/cache inspection | NO-GO |
| R-09 | Development authentication in release | Production startup guards and OIDC proxy | Configuration tests | NO-GO |
| R-10 | AI abstention misread as normal | AI disabled; no normal/negative conclusion | UI/API tests | NO-GO |
| R-11 | Data loss during upgrade | Backup/restore and rollback rehearsal | Restore drill | NO-GO |
| R-12 | Resource exhaustion | Upload, study and container limits | Large-study/concurrency test | NO-GO |

The owner must add residual-risk decisions, evidence links, and reviewer names before release. Risks cannot be accepted by deleting or weakening a failed test.
