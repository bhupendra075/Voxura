"""Exercise the import path against an independently described synthetic source."""

import hashlib
import json

import pydicom
from fastapi.testclient import TestClient

import app
from tools.build_synthetic_reference import build


def test_synthetic_reference_import_preserves_sources_and_geometry(tmp_path):
    manifest = json.loads(build(tmp_path).read_text(encoding="utf-8"))
    assert manifest["clinical_data_root"] is False
    client = TestClient(app.app)
    token = client.post("/v3/session/dev").json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    source = {item["sha256"]: (tmp_path / item["relative_path"]).read_bytes()
              for item in manifest["files"]}
    for item in manifest["files"]:
        payload = source[item["sha256"]]
        assert len(payload) == item["bytes"]
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
        dataset = pydicom.dcmread(tmp_path / item["relative_path"])
        assert int(dataset.pixel_array.min()) == item["pixel_min"]
        assert int(dataset.pixel_array.max()) == item["pixel_max"]

    # Reverse upload order; the viewer must follow patient geometry.
    response = client.post("/v3/import", headers=auth, files=[
        ("files", (item["relative_path"], source[item["sha256"]], "application/dicom"))
        for item in reversed(manifest["files"])
    ])
    assert response.status_code == 201
    accepted = response.json()["accepted"]
    assert len(accepted) == len(source)
    assert response.json()["rejected"] == []
    assert {item["sha256"] for item in accepted} == set(source)
    study_id = accepted[0]["study_id"]
    viewer = client.get(f"/v3/studies/{study_id}/viewer-manifest", headers=auth)
    assert viewer.status_code == 200
    series = viewer.json()["series"][0]
    assert series["ordering"] == "patient_geometry"
    assert series["measurement_calibrated"] is True
    assert [item["geometry_position"] for item in series["instances"]] == [-2, 0, 2]
    assert series["instance_count"] == len(manifest["files"])
    for expected, item in zip(manifest["files"], series["instances"], strict=True):
        assert item["sha256"] == expected["sha256"]
        assert [float(value) for value in item["orientation"]] == manifest["orientation_patient"]
        assert [float(value) for value in item["pixel_spacing"]] == manifest["pixel_spacing_mm"]
        assert float(item["window_center"]) == manifest["window_center"]
        assert float(item["window_width"]) == manifest["window_width"]
        stored = client.get(item["dicom_url"], headers=auth)
        assert stored.status_code == 200
        assert stored.content == source[item["sha256"]]
        decoded = pydicom.dcmread(tmp_path / expected["relative_path"])
        rescaled = decoded.pixel_array * float(decoded.RescaleSlope) + float(decoded.RescaleIntercept)
        assert rescaled.min() == expected["rescaled_min"]
        assert rescaled.max() == expected["rescaled_max"]
