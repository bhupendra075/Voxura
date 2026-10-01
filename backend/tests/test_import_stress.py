from __future__ import annotations

import hashlib
import time
import tracemalloc
from io import BytesIO

import numpy as np
from fastapi.testclient import TestClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

import app


client = TestClient(app.app)


def _token() -> str:
    response = client.post("/v3/session/dev")
    assert response.status_code == 200
    return response.json()["access_token"]


def _mr_slice(
    study_uid: str,
    series_uid: str,
    index: int,
    *,
    sop_uid: str | None = None,
    cross_chunk_boundary: bool = False,
) -> bytes:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = sop_uid or generate_uid()
    dataset = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = series_uid
    dataset.Modality = "MR"
    dataset.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    dataset.ImagePositionPatient = ["0", "0", str(index * 0.75)]
    dataset.PatientName = "SYNTHETIC^STRESS"
    dataset.PatientID = "SYNTHETIC-STRESS-001"
    dataset.PatientBirthDate = "19000101"
    dataset.PatientSex = "O"
    dataset.AccessionNumber = "SYNTHETIC-ONLY"
    dataset.StudyDate = "20260930"
    dataset.StudyDescription = "Synthetic import stress fixture"
    dataset.SeriesDescription = "Synthetic axial MR"
    dataset.SeriesNumber = 1
    # Reverse instance numbers so geometry, not upload or InstanceNumber, controls stack order.
    dataset.InstanceNumber = 512 - index
    dataset.Rows = 16
    dataset.Columns = 16
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 12
    dataset.HighBit = 11
    dataset.PixelRepresentation = 0
    dataset.PixelSpacing = [0.75, 0.75]
    dataset.PixelData = np.full((16, 16), index % 4096, dtype=np.uint16).tobytes()
    if cross_chunk_boundary:
        # Synthetic non-pixel padding makes one source span multiple 1 MiB reads without
        # inflating all 512 instances or changing the diagnostic pixel matrix.
        dataset.add_new((0x7777, 0x0010), "OB", b"\0" * (1024 * 1024 + 17))
    output = BytesIO()
    dataset.save_as(output, enforce_file_format=True)
    return output.getvalue()


def test_512_slice_import_is_ordered_bounded_explicit_and_immutable():
    auth = {"Authorization": f"Bearer {_token()}"}
    study_uid, series_uid = generate_uid(), generate_uid()
    payloads = [
        _mr_slice(study_uid, series_uid, index, cross_chunk_boundary=index == 0)
        for index in range(512)
    ]
    assert len(payloads[0]) > 1024 * 1024
    expected_hashes = [hashlib.sha256(payload).hexdigest() for payload in payloads]

    # Add an exact duplicate and a malformed object to exercise mixed-result behavior.
    files = [
        ("files", (f"slice-{index:04d}.dcm", payload, "application/dicom"))
        for index, payload in enumerate(payloads)
    ]
    files.extend([
        ("files", ("duplicate.dcm", payloads[0], "application/dicom")),
        ("files", ("malformed.dcm", b"not a dicom object", "application/dicom")),
    ])

    tracemalloc.start()
    started = time.perf_counter()
    response = client.post("/v3/import", headers=auth, files=files)
    elapsed = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert response.status_code == 201
    result = response.json()
    imported = [item for item in result["accepted"] if item["status"] == "imported"]
    duplicates = [item for item in result["accepted"] if item["status"] == "duplicate"]
    assert len(imported) == 512
    assert len(duplicates) == 1
    assert duplicates[0]["sha256"] == expected_hashes[0]
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["status"] == "rejected"
    assert result["rejected"][0]["code"] == "invalid_dicom"
    assert result["limits"]["files"] >= len(files)

    manifest_response = client.get(
        f"/v3/studies/{imported[0]['study_id']}/viewer-manifest", headers=auth
    )
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    stack = manifest["series"][0]
    assert stack["instance_count"] == 512
    assert stack["ordering"] == "patient_geometry"
    assert [item["geometry_position"] for item in stack["instances"]] == [
        index * 0.75 for index in range(512)
    ]
    assert {item["sha256"] for item in stack["instances"]} == set(expected_hashes)

    # Re-read representative stored objects byte-for-byte after the mixed import.
    accepted_by_hash = {item["sha256"]: item for item in imported}
    for index in (0, 255, 511):
        stored = client.get(
            f"/v3/instances/{accepted_by_hash[expected_hashes[index]]['instance_id']}/dicom",
            headers=auth,
        )
        assert stored.status_code == 200
        assert stored.content == payloads[index]
        assert hashlib.sha256(stored.content).hexdigest() == expected_hashes[index]
        assert stored.headers["x-source-immutable"] == "true"

    # Observational evidence only: deliberately no machine-dependent pass/fail threshold.
    print(
        f"512-slice synthetic import: {elapsed:.3f}s, "
        f"tracemalloc peak {peak_bytes / (1024 * 1024):.1f} MiB"
    )
