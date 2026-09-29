from io import BytesIO
from uuid import uuid4
import time

import jwt
import numpy as np
from fastapi.testclient import TestClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

import app
import clinical

client = TestClient(app.app)


def token() -> str:
    response = client.post("/v3/session/dev")
    assert response.status_code == 200
    return response.json()["access_token"]


def dicom_bytes(modality="DX") -> tuple[bytes, str]:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    dataset = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.Modality = modality
    dataset.PatientName = "TEST^FIXTURE"
    dataset.PatientID = f"TEST-{uuid4().hex[:8]}"
    dataset.PatientBirthDate = "19800101"
    dataset.PatientSex = "O"
    dataset.AccessionNumber = "DEMO-001"
    dataset.StudyDate = "20260929"
    dataset.StudyDescription = "De-identified validation study"
    dataset.SeriesDescription = "Validation images"
    dataset.SeriesNumber = 1
    dataset.InstanceNumber = 1
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
    assert client.put(f"/v3/studies/{study_id}/presentation-state", headers=auth, json=state).status_code == 200
    assert client.get(f"/v3/studies/{study_id}/presentation-state", headers=auth).json()["zoom"] == 1.5


def test_rejects_unsupported_modality_without_silent_import():
    auth = {"Authorization": f"Bearer {token()}"}
    payload, _ = dicom_bytes("US")
    response = client.post("/v3/import", headers=auth, files=[("files", ("ultrasound.dcm", payload, "application/dicom"))])
    assert response.status_code == 201
    assert response.json()["accepted"] == []
    assert "Unsupported modality" in response.json()["rejected"][0]["reason"]


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
