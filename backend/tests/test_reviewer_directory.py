from __future__ import annotations

from fastapi.testclient import TestClient

import app
import clinical
from test_auth_boundary import _proxy_headers


client = TestClient(app.app)


def test_reviewer_directory_requires_admin_and_is_tenant_scoped(monkeypatch):
    monkeypatch.setattr(clinical, "AUTH_MODE", "proxy")
    monkeypatch.setattr(clinical, "TRUSTED_PROXY_SECRET", "test-proxy-secret-that-is-long-enough")
    item = {"name": "Site Reviewer", "affiliation": "Site A", "expertise": "CT display", "source_url": ""}

    assert client.post("/v3/reviewers", headers=_proxy_headers(role="radiologist"), json=item).status_code == 403
    assert client.get("/v3/reviewers", headers=_proxy_headers(role="radiologist")).status_code == 403

    created = client.post("/v3/reviewers", headers=_proxy_headers(role="administrator"), json=item)
    assert created.status_code == 201
    assert created.json()["status"] == "proposed"

    site_a = client.get("/v3/reviewers", headers=_proxy_headers(role="administrator"))
    site_b = client.get("/v3/reviewers", headers=_proxy_headers(role="administrator", institution="SITE-B"))
    assert site_a.status_code == site_b.status_code == 200
    assert any(row["id"] == created.json()["id"] for row in site_a.json()["items"])
    assert all(row["id"] != created.json()["id"] for row in site_b.json()["items"])
