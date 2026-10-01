from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "controlled-pilot"
REQUIRED = [
    "INTENDED_USE.md", "SUPPORTED_DICOM.md", "RELEASE_GATES.md",
    "RISK_REGISTER.md", "CHECKPOINT.md", "FIXTURE_PROVENANCE.template.json",
    "DEPLOYMENT.md", "BACKUP_RESTORE_ROLLBACK.md", "release-evidence.template.json",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


for name in REQUIRED:
    path = DOCS / name
    if not path.is_file() or path.stat().st_size < 80:
        fail(f"missing or empty controlled-pilot evidence file: {path.relative_to(ROOT)}")

intended = (DOCS / "INTENDED_USE.md").read_text(encoding="utf-8")
for phrase in ("CONTROLLED EVALUATION ONLY", "DE-IDENTIFIED", "does not provide diagnoses"):
    if phrase not in intended:
        fail(f"intended-use document is missing: {phrase}")

fixture = json.loads((DOCS / "FIXTURE_PROVENANCE.template.json").read_text(encoding="utf-8"))
if fixture.get("clinical_data_root") is not False or "evaluation" not in fixture.get("allowed_use", ""):
    fail("fixture provenance template does not enforce evaluation isolation")

compose = (ROOT / "ops" / "compose.yaml").read_text(encoding="utf-8")
for unsafe in ("CLINICAL_DEV_MODE: \"1\"", "sqlite://", "PACS_BEARER_TOKEN"):
    if unsafe in compose:
        fail(f"unsafe production compose content: {unsafe}")
for required in (
    "condition: service_healthy", "condition: service_completed_successfully",
    "no-new-privileges:true", "internal: true", "/ready", "read_only: true",
    "CLINICAL_TRUSTED_PROXY_MAX_AGE_SECONDS", "CLINICAL_MAX_DICOM_BYTES",
    "CLINICAL_MAX_IMPORT_FILES", "CLINICAL_MAX_IMPORT_BYTES",
    "pids_limit:", "mem_limit:", "cpus:",
):
    if required not in compose:
        fail(f"compose is missing safety control: {required}")

env_example = (ROOT / "ops" / ".env.example").read_text(encoding="utf-8")
for required in (
    "POSTGRES_PASSWORD=REPLACE_WITH_SECRET_MANAGER_VALUE",
    "CLINICAL_TRUSTED_PROXY_SECRET=REPLACE_WITH_AT_LEAST_32_RANDOM_BYTES",
    "VOXURA_BIND_ADDRESS=127.0.0.1",
):
    if required not in env_example:
        fail(f"environment template is missing fail-closed default: {required}")

nginx = (ROOT / "ops" / "docker" / "nginx.conf").read_text(encoding="utf-8")
for required in (
    'X-Voxura-User ""', 'X-Voxura-Role ""', 'X-Voxura-Institution ""',
    'X-Voxura-Timestamp ""', 'X-Voxura-Signature ""',
    'Cache-Control "private, no-store"', "proxy_request_buffering off",
):
    if required not in nginx:
        fail(f"bundled proxy is missing identity/cache safety control: {required}")

for dockerfile in ("backend.Dockerfile", "frontend.Dockerfile"):
    text = (ROOT / "ops" / "docker" / dockerfile).read_text(encoding="utf-8")
    if ":latest" in text:
        fail(f"{dockerfile} uses a floating latest image tag")
if "USER voxura" not in (ROOT / "ops" / "docker" / "backend.Dockerfile").read_text(encoding="utf-8"):
    fail("backend image does not run as the unprivileged voxura user")
if "npm ci" not in (ROOT / "ops" / "docker" / "frontend.Dockerfile").read_text(encoding="utf-8"):
    fail("frontend image does not use the lockfile-enforcing npm ci install")

for script_name in ("backup.ps1", "restore.ps1"):
    script = (ROOT / "ops" / "scripts" / script_name).read_text(encoding="utf-8")
    for required in ("docker compose", "$LASTEXITCODE", "database:", "finally"):
        if required not in script:
            fail(f"{script_name} is missing checked binary-safe database handling: {required}")

gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
for required in ("ops/.env", "ops/backups/"):
    if required not in gitignore:
        fail(f"secret or backup path is not ignored: {required}")

runtime_env_path = ROOT / "ops" / ".env"
if runtime_env_path.exists():
    runtime_env = parse_env(runtime_env_path)
    placeholders = {
        "POSTGRES_PASSWORD": "REPLACE_WITH_SECRET_MANAGER_VALUE",
        "CLINICAL_TRUSTED_PROXY_SECRET": "REPLACE_WITH_AT_LEAST_32_RANDOM_BYTES",
    }
    for key, placeholder in placeholders.items():
        value = runtime_env.get(key, "")
        if not value or value == placeholder:
            fail(f"ops/.env has an unset or placeholder value for {key}")
    if len(runtime_env["CLINICAL_TRUSTED_PROXY_SECRET"]) < 32:
        fail("ops/.env CLINICAL_TRUSTED_PROXY_SECRET must contain at least 32 characters")
    if any(character in runtime_env["POSTGRES_PASSWORD"] for character in ":/@?#[]"):
        fail("POSTGRES_PASSWORD contains URI-reserved characters; use a URL-safe generated secret")

evidence = json.loads((DOCS / "release-evidence.template.json").read_text(encoding="utf-8"))
if {gate["status"] for gate in evidence["gates"]} != {"NOT_RUN"}:
    fail("release evidence template must default every gate to NOT_RUN")

digest = hashlib.sha256()
for path in sorted((DOCS / name for name in REQUIRED), key=lambda p: p.name):
    digest.update(path.read_bytes())
print(json.dumps({"status": "pass", "evidence_document_sha256": digest.hexdigest(), "files": len(REQUIRED)}))
