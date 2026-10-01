from __future__ import annotations

import os
import subprocess
import sys
import time

from fastapi.testclient import TestClient

import app
import clinical


client = TestClient(app.app)


def _proxy_headers(user: str = "reader-1", role: str = "radiologist", institution: str = "SITE-A",
                   timestamp: str | None = None) -> dict[str, str]:
    timestamp = timestamp or str(int(time.time()))
    return {
        "X-Voxura-User": user,
        "X-Voxura-Role": role,
        "X-Voxura-Institution": institution,
        "X-Voxura-Timestamp": timestamp,
        "X-Voxura-Signature": clinical._proxy_signature(user, role, institution, timestamp),
    }


def test_proxy_mode_rejects_missing_and_untrusted_identity(monkeypatch):
    monkeypatch.setattr(clinical, "AUTH_MODE", "proxy")
    monkeypatch.setattr(clinical, "TRUSTED_PROXY_SECRET", "test-proxy-secret-that-is-long-enough")
    missing = client.get("/v3/session")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "trusted_identity_required"

    forged = _proxy_headers()
    forged["X-Voxura-Signature"] = "0" * 64
    rejected = client.get("/v3/session", headers=forged)
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "untrusted_proxy_identity"


def test_proxy_mode_accepts_scoped_identity_and_rejects_unknown_role(monkeypatch):
    monkeypatch.setattr(clinical, "AUTH_MODE", "proxy")
    monkeypatch.setattr(clinical, "TRUSTED_PROXY_SECRET", "test-proxy-secret-that-is-long-enough")
    accepted = client.get("/v3/session", headers=_proxy_headers())
    assert accepted.status_code == 200
    assert accepted.json()["institution"] == "SITE-A"
    assert accepted.json()["user"]["role"] == "radiologist"

    rejected = client.get("/v3/session", headers=_proxy_headers(role="superuser"))
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "invalid_role"


def test_proxy_mode_rejects_stale_and_tampered_scoped_identity(monkeypatch):
    monkeypatch.setattr(clinical, "AUTH_MODE", "proxy")
    monkeypatch.setattr(clinical, "TRUSTED_PROXY_SECRET", "test-proxy-secret-that-is-long-enough")
    stale = _proxy_headers(timestamp=str(int(time.time()) - clinical.TRUSTED_PROXY_MAX_AGE_SECONDS - 1))
    response = client.get("/v3/session", headers=stale)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "stale_proxy_identity"

    signed = _proxy_headers(institution="SITE-A")
    signed["X-Voxura-Institution"] = "SITE-B"
    response = client.get("/v3/session", headers=signed)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "untrusted_proxy_identity"


def test_clinician_role_cannot_import(monkeypatch):
    monkeypatch.setattr(clinical, "AUTH_MODE", "proxy")
    monkeypatch.setattr(clinical, "TRUSTED_PROXY_SECRET", "test-proxy-secret-that-is-long-enough")
    response = client.post(
        "/v3/import",
        headers=_proxy_headers(role="clinician"),
        files=[("files", ("not-read.dcm", b"not-a-dicom", "application/dicom"))],
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "import_forbidden"


def test_development_session_is_hidden_in_proxy_mode(monkeypatch):
    monkeypatch.setattr(clinical, "AUTH_MODE", "proxy")
    monkeypatch.setattr(clinical, "DEV_MODE", True)
    assert client.post("/v3/session/dev").status_code == 404


def test_production_configuration_fails_closed_without_proxy_secret(tmp_path):
    environment = os.environ.copy()
    environment.update({
        "CLINICAL_ENV": "production",
        "CLINICAL_DEV_MODE": "0",
        "CLINICAL_AUTH_MODE": "proxy",
        "CLINICAL_DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
        "CLINICAL_DATA_ROOT": str(tmp_path),
        "CLINICAL_TRUSTED_PROXY_SECRET": "",
    })
    result = subprocess.run(
        [sys.executable, "-c", "import clinical"],
        cwd=os.path.dirname(clinical.__file__),
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "CLINICAL_TRUSTED_PROXY_SECRET" in result.stderr
