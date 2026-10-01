from io import BytesIO
from uuid import uuid4
import time

import jwt
import numpy as np
import pydicom
import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import DigitalXRayImageStorageForPresentation, ExplicitVRLittleEndian, MRImageStorage, SecondaryCaptureImageStorage, generate_uid

import app
import clinical

client = TestClient(app.app)


def token() -> str:
    response = client.post("/v3/session/dev")
    assert response.status_code == 200
    return response.json()["access_token"]


def dicom_bytes(modality="DX", series_description="Validation images", *, study_uid=None,
                series_uid=None, instance_number=1, position=0.0) -> tuple[bytes, str]:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage if modality == "MR" else DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID = generate_uid()
    dataset = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = study_uid or generate_uid()
    dataset.SeriesInstanceUID = series_uid or generate_uid()
    dataset.Modality = modality
    dataset.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    dataset.ImagePositionPatient = ["0", "0", str(position)]
    dataset.PatientName = "TEST^FIXTURE"
    dataset.PatientID = f"TEST-{uuid4().hex[:8]}"
    dataset.PatientBirthDate = "19800101"
    dataset.PatientSex = "O"
    dataset.AccessionNumber = "DEMO-001"
    dataset.StudyDate = "20260929"
    dataset.StudyDescription = "De-identified validation study"
    dataset.SeriesDescription = series_description
    dataset.SeriesNumber = 1
    dataset.InstanceNumber = instance_number
    dataset.Rows = 8
    dataset.Columns = 8
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 12
    dataset.HighBit = 11
    dataset.PixelRepresentation = 0
    dataset.PixelSpacing = [0.5, 0.5]
    dataset.PixelData = np.arange(64, dtype=np.uint16).reshape(8, 8).tobytes()
    output = BytesIO(); dataset.save_as(output, enforce_file_format=True)
    return output.getvalue(), dataset.PatientID


def with_geometry(payload: bytes, *, orientation=None, position=None, pixel_spacing=None) -> bytes:
    dataset = pydicom.dcmread(BytesIO(payload))
    if orientation is not None:
        dataset.ImageOrientationPatient = [str(value) for value in orientation]
    if position is not None:
        dataset.ImagePositionPatient = [str(value) for value in position]
    if pixel_spacing is not None:
        dataset.PixelSpacing = [str(value) for value in pixel_spacing]
    output = BytesIO(); dataset.save_as(output, enforce_file_format=True)
    return output.getvalue()


def test_v3_requires_authentication():
    assert client.get("/v3/studies").status_code == 401


def test_dicom_import_browse_render_and_presentation_state():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, patient_id = dicom_bytes()
    imported = client.post("/v3/import", headers=auth, files=[("files", ("study.dcm", payload, "application/dicom"))])
    assert imported.status_code == 201
    assert len(imported.json()["accepted"]) == 1
    study_id = imported.json()["accepted"][0]["study_id"]

    studies = client.get(f"/v3/studies?patient={patient_id}", headers=auth).json()["items"]
    assert studies[0]["patient_id"] == patient_id
    series = client.get(f"/v3/studies/{study_id}/series", headers=auth).json()["items"]
    metadata = client.get(f"/v3/studies/{study_id}/series/{series[0]['id']}/metadata", headers=auth).json()
    instance_id = metadata["instances"][0]["id"]
    rendered = client.get(f"/v3/instances/{instance_id}/frames/0/rendered", headers=auth)
    assert rendered.status_code == 200
    assert rendered.headers["content-type"] == "image/png"
    assert rendered.headers["x-source-immutable"] == "true"

    state = {"layout": "1x2", "active_series_id": series[0]["id"], "active_instance_id": instance_id,
             "frame": 0, "zoom": 1.5, "pan_x": 0, "pan_y": 0, "rotation": 0,
             "inverted": False, "annotations": []}
    saved = client.put(f"/v3/studies/{study_id}/presentation-state", headers=auth, json=state)
    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert client.get(f"/v3/studies/{study_id}/presentation-state", headers=auth).json()["zoom"] == 1.5
    assert client.put(f"/v3/studies/{study_id}/presentation-state", headers=auth, json=state).status_code == 409


def test_presentation_state_restores_per_user_and_study_with_full_viewport_state():
    auth = {"Authorization": f"Bearer {token()}"}
    study_uid, series_uid = generate_uid(), generate_uid()
    first, _ = dicom_bytes("MR", study_uid=study_uid, series_uid=series_uid, instance_number=1, position=0)
    second, _ = dicom_bytes("MR", study_uid=study_uid, series_uid=series_uid, instance_number=2, position=1)
    imported = client.post("/v3/import", headers=auth, files=[
        ("files", ("one.dcm", first, "application/dicom")),
        ("files", ("two.dcm", second, "application/dicom")),
    ]).json()["accepted"]
    study_id, series_id = imported[0]["study_id"], imported[0]["series_id"]
    annotation = {"metadata": {"toolName": "Length"}, "data": {"handles": {"points": [[0, 0, 0], [1, 1, 0]]}}}
    state = {"version": 0, "layout": "1x1", "active_series_id": series_id,
             "active_instance_id": imported[1]["instance_id"], "frame": 0,
             "window_center": 450.5, "window_width": 900.0, "zoom": 2.25,
             "pan_x": 21.5, "pan_y": -9.25, "rotation": 0, "inverted": True,
             "annotations": [annotation]}
    saved = client.put(f"/v3/studies/{study_id}/presentation-state", headers=auth, json=state)
    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    restored = client.get(f"/v3/studies/{study_id}/presentation-state", headers=auth).json()
    assert restored == {**state, "version": 1}

    now = int(time.time())
    second_user_token = jwt.encode({"sub": "second-radiologist", "role": "radiologist", "institution": "DEMO",
                                    "aud": "clinical-viewer", "iat": now, "exp": now + 3600},
                                   clinical.JWT_SECRET, algorithm="HS256")
    second_user_auth = {"Authorization": f"Bearer {second_user_token}"}
    assert client.get(f"/v3/studies/{study_id}/presentation-state", headers=second_user_auth).json()["version"] == 0

    other_payload, _ = dicom_bytes("MR")
    other = client.post("/v3/import", headers=auth, files=[("files", ("other.dcm", other_payload, "application/dicom"))]).json()["accepted"][0]
    assert client.get(f"/v3/studies/{other['study_id']}/presentation-state", headers=auth).json()["version"] == 0
    invalid = {**state, "version": 1, "active_series_id": other["series_id"], "active_instance_id": other["instance_id"]}
    response = client.put(f"/v3/studies/{study_id}/presentation-state", headers=auth, json=invalid)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_presentation_series"


def test_session_health_manifest_and_raw_dicom_range():
    auth = {"Authorization": f"Bearer {token()}"}
    assert client.get("/health").json() == {"status": "alive"}
    assert client.get("/ready").status_code == 200
    session = client.get("/v3/session", headers=auth)
    assert session.status_code == 200
    assert session.json()["evaluation_only"] is True
    payload, _ = dicom_bytes("MR")
    imported = client.post("/v3/import", headers=auth, files=[("files", ("manifest.dcm", payload, "application/dicom"))]).json()
    study_id = imported["accepted"][0]["study_id"]
    instance_id = imported["accepted"][0]["instance_id"]
    manifest = client.get(f"/v3/studies/{study_id}/viewer-manifest", headers=auth)
    assert manifest.status_code == 200
    assert manifest.json()["series"][0]["ordering"] == "patient_geometry"
    assert manifest.json()["series"][0]["has_pixel_spacing"] is True
    assert manifest.json()["series"][0]["measurement_calibrated"] is True
    source = client.get(f"/v3/instances/{instance_id}/dicom", headers={**auth, "Range": "bytes=0-31"})
    assert source.status_code == 206
    assert len(source.content) == 32
    assert source.headers["cache-control"] == "private, no-store"
    assert source.headers["x-source-immutable"] == "true"
    assert source.headers["content-range"].startswith("bytes 0-31/")
    assert source.headers["accept-ranges"] == "bytes"

    invalid_range = client.get(
        f"/v3/instances/{instance_id}/dicom",
        headers={**auth, "Range": "bytes=999999999-1000000000"},
    )
    assert invalid_range.status_code == 416
    assert invalid_range.headers["cache-control"] == "private, no-store"


def test_import_to_viewer_manifest_preserves_source_and_uses_geometry_order():
    auth = {"Authorization": f"Bearer {token()}"}
    study_uid, series_uid = generate_uid(), generate_uid()
    # Upload and InstanceNumber order intentionally disagree with patient geometry.
    high, _ = dicom_bytes("MR", study_uid=study_uid, series_uid=series_uid, instance_number=1, position=10)
    low, _ = dicom_bytes("MR", study_uid=study_uid, series_uid=series_uid, instance_number=2, position=-10)
    response = client.post("/v3/import", headers=auth, files=[
        ("files", ("high.dcm", high, "application/dicom")),
        ("files", ("low.dcm", low, "application/dicom")),
    ])
    assert response.status_code == 201
    accepted = response.json()["accepted"]
    assert len(accepted) == 2
    manifest = client.get(f"/v3/studies/{accepted[0]['study_id']}/viewer-manifest", headers=auth).json()
    stack = manifest["series"][0]
    assert stack["ordering"] == "patient_geometry"
    assert [item["geometry_position"] for item in stack["instances"]] == [-10.0, 10.0]
    source_by_id = {accepted[0]["instance_id"]: high, accepted[1]["instance_id"]: low}
    for item in stack["instances"]:
        source = client.get(item["dicom_url"], headers=auth)
        assert source.status_code == 200
        assert source.content == source_by_id[item["id"]]
        assert source.headers["cache-control"] == "private, no-store"


def test_geometry_accepts_orthonormal_cardinal_and_oblique_orientations():
    cases = [
        ([1, 0, 0, 0, 1, 0], [0, 0, 7], 7.0),       # axial
        ([1, 0, 0, 0, 0, -1], [0, 5, 0], 5.0),      # coronal
        ([0, 1, 0, 0, 0, -1], [-3, 0, 0], 3.0),     # sagittal
        ([2 ** -0.5, 2 ** -0.5, 0, 0, 0, 1], [2, -2, 0], 2 * 2 ** 0.5),
    ]
    for orientation, position, expected in cases:
        metadata = {"ImageOrientationPatient": orientation, "ImagePositionPatient": position}
        assert clinical._geometry_position(metadata) == pytest.approx(expected, abs=1e-6)


def test_geometry_rejects_missing_non_unit_parallel_and_non_orthogonal_vectors():
    invalid = [
        {"ImagePositionPatient": [0, 0, 0]},
        {"ImageOrientationPatient": [2, 0, 0, 0, 1, 0], "ImagePositionPatient": [0, 0, 0]},
        {"ImageOrientationPatient": [1, 0, 0, 1, 0, 0], "ImagePositionPatient": [0, 0, 0]},
        {"ImageOrientationPatient": [1, 0, 0, 0.1, 0.995, 0], "ImagePositionPatient": [0, 0, 0]},
    ]
    assert all(clinical._geometry_position(metadata) is None for metadata in invalid)


def test_pixel_spacing_requires_positive_finite_components_and_allows_anisotropy():
    assert clinical._valid_pixel_spacing([0.4, 1.2]) == [0.4, 1.2]
    for value in (None, [0.5], [0, 0.5], [-0.5, 0.5], [float("nan"), 0.5], [float("inf"), 0.5]):
        assert clinical._valid_pixel_spacing(value) is None
    assert clinical._consistent_pixel_spacing([[0.4, 1.2], [0.4, 1.2]]) is True
    assert clinical._consistent_pixel_spacing([[0.4, 1.2], [0.4, 1.3]]) is False
    assert clinical._consistent_pixel_spacing([[0.4, 1.2], [0, 1.2]]) is False
    assert clinical._consistent_pixel_spacing([]) is False


def test_manifest_falls_back_for_inconsistent_orientation_and_blocks_bad_spacing():
    auth = {"Authorization": f"Bearer {token()}"}
    study_uid, series_uid = generate_uid(), generate_uid()
    first, _ = dicom_bytes("MR", study_uid=study_uid, series_uid=series_uid, instance_number=1, position=0)
    second, _ = dicom_bytes("MR", study_uid=study_uid, series_uid=series_uid, instance_number=2, position=1)
    second = with_geometry(
        second,
        orientation=[1, 0, 0, 0, 0, -1],
        position=[0, 1, 0],
        pixel_spacing=[0, 0.5],
    )
    imported = client.post("/v3/import", headers=auth, files=[
        ("files", ("first.dcm", first, "application/dicom")),
        ("files", ("second.dcm", second, "application/dicom")),
    ]).json()
    manifest = client.get(
        f"/v3/studies/{imported['accepted'][0]['study_id']}/viewer-manifest", headers=auth
    ).json()
    series = manifest["series"][0]
    assert series["ordering"] == "instance_number_fallback"
    assert series["measurement_calibrated"] is False
    assert any("Spatial geometry is incomplete" in warning for warning in series["warnings"])
    assert any("calibrated measurements are disabled" in warning for warning in series["warnings"])


def test_import_duplicate_is_explicit_and_does_not_replace_source():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("MR")
    first = client.post("/v3/import", headers=auth, files=[("files", ("first.dcm", payload, "application/dicom"))]).json()
    second = client.post("/v3/import", headers=auth, files=[("files", ("second.dcm", payload, "application/dicom"))]).json()
    assert first["accepted"][0]["status"] == "imported"
    assert second["accepted"][0]["status"] == "duplicate"
    assert first["accepted"][0]["sha256"] == second["accepted"][0]["sha256"]


def test_rejects_unsupported_modality_without_silent_import():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("US")
    response = client.post("/v3/import", headers=auth, files=[("files", ("ultrasound.dcm", payload, "application/dicom"))])
    assert response.status_code == 201
    assert response.json()["accepted"] == []
    assert "Unsupported modality" in response.json()["rejected"][0]["reason"]


def test_rejects_secondary_capture_even_when_it_claims_a_supported_modality():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("MR")
    dataset = pydicom.dcmread(BytesIO(payload))
    dataset.SOPClassUID = SecondaryCaptureImageStorage
    dataset.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    rewritten = BytesIO(); dataset.save_as(rewritten, enforce_file_format=True)
    response = client.post("/v3/import", headers=auth, files=[("files", ("secondary.dcm", rewritten.getvalue(), "application/dicom"))])
    assert response.status_code == 201
    assert response.json()["accepted"] == []
    assert "SOP Class" in response.json()["rejected"][0]["reason"]


def test_analysis_abstains_when_no_validated_model_is_enabled():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("MR")
    imported = client.post("/v3/import", headers=auth, files=[("files", ("brain-mri.dcm", payload, "application/dicom"))])
    study_id = imported.json()["accepted"][0]["study_id"]
    response = client.post(f"/v3/studies/{study_id}/analysis-jobs", headers=auth, json={"profile": "brain_mri_assist_v1"})
    assert response.status_code == 202
    assert response.json()["state"] == "abstained"
    assert "No clinically validated" in response.json()["message"]
    assert response.json()["manifest"]["series_count"] == 1


def test_analysis_manifest_recognizes_stir_sequence():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("MR", "Brain STIR axial")
    imported = client.post("/v3/import", headers=auth, files=[("files", ("stir.dcm", payload, "application/dicom"))])
    study_id = imported.json()["accepted"][0]["study_id"]
    response = client.post(f"/v3/studies/{study_id}/analysis-jobs", headers=auth, json={"profile": "brain_mri_assist_v1"})
    assert response.status_code == 202
    assert "STIR" in response.json()["manifest"]["sequences"]


def test_report_draft_requires_optimistic_version_and_review_checklist():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("MR")
    imported = client.post("/v3/import", headers=auth, files=[("files", ("draft-study.dcm", payload, "application/dicom"))])
    study_id = imported.json()["accepted"][0]["study_id"]
    draft = client.put(f"/v3/studies/{study_id}/report-draft", headers=auth, json={
        "version": 0, "findings_text": "Evidence-linked draft finding.", "impression_text": "Radiologist review required.",
    })
    assert draft.status_code == 200
    assert draft.json()["version"] == 1
    conflict = client.put(f"/v3/studies/{study_id}/report-draft", headers=auth, json={
        "version": 0, "findings_text": "stale", "impression_text": "stale",
    })
    assert conflict.status_code == 409
    incomplete = client.post(f"/v3/studies/{study_id}/report-draft/review", headers=auth, json={
        "version": 1, "patient_identity_confirmed": True, "laterality_checked": True,
        "priors_checked": True, "critical_findings_checked": True, "warnings_resolved": False,
    })
    assert incomplete.status_code == 422


def test_studies_and_instances_are_tenant_scoped():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("MR")
    imported = client.post("/v3/import", headers=auth, files=[("files", ("tenant-study.dcm", payload, "application/dicom"))]).json()
    study_id = imported["accepted"][0]["study_id"]
    series_id = client.get(f"/v3/studies/{study_id}/series", headers=auth).json()["items"][0]["id"]
    instance_id = client.get(f"/v3/studies/{study_id}/series/{series_id}/metadata", headers=auth).json()["instances"][0]["id"]
    now = int(time.time())
    other = jwt.encode({"sub": "other-user", "role": "radiologist", "institution": "OTHER",
                        "aud": "clinical-viewer", "iat": now, "exp": now + 3600}, clinical.JWT_SECRET, algorithm="HS256")
    other_auth = {"Authorization": f"Bearer {other}"}
    assert client.get(f"/v3/studies/{study_id}/series", headers=other_auth).status_code == 404
    assert client.get(f"/v3/instances/{instance_id}/dicom", headers=other_auth).status_code == 404
    assert client.get(f"/v3/studies/{study_id}/presentation-state", headers=other_auth).status_code == 404
    state = {"version": 0, "layout": "1x1", "frame": 0, "zoom": 1, "pan_x": 0,
             "pan_y": 0, "rotation": 0, "inverted": False, "annotations": []}
    assert client.put(
        f"/v3/studies/{study_id}/presentation-state", headers=other_auth, json=state
    ).status_code == 404


def test_safe_errors_are_redacted_and_audit_rows_are_append_only():
    auth = {"Authorization": f"Bearer {token()}"}
    missing = client.get("/v3/instances/not-a-real-instance/dicom", headers=auth)
    assert missing.status_code == 404
    body = missing.json()["error"]
    assert body["code"] == "instance_not_found"
    assert "SELECT" not in body["message"]
    assert body["request_id"]

    client.get("/v3/studies", headers=auth)
    with clinical._db() as connection:
        event = connection.execute("SELECT id FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
        assert event is not None
        try:
            connection.execute("UPDATE audit_events SET outcome=? WHERE id=?", ("tampered", event["id"]))
        except Exception as exc:
            assert "immutable" in str(exc).lower()
        else:
            raise AssertionError("audit event update unexpectedly succeeded")
