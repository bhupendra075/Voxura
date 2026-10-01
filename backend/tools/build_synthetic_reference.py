"""Build a deterministic, synthetic DICOM reference for non-clinical gate checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian


UID_ROOT = "1.2.826.0.1.3680043.10.543.20261001"


def build(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for index, position in enumerate((-2, 0, 2), start=1):
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = f"{UID_ROOT}.3.{index}"
        dataset = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
        dataset.SOPClassUID = CTImageStorage
        dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        dataset.StudyInstanceUID = f"{UID_ROOT}.1"
        dataset.SeriesInstanceUID = f"{UID_ROOT}.2"
        dataset.Modality = "CT"
        dataset.PatientName = "SYNTHETIC^REFERENCE"
        dataset.PatientID = "SYNTHETIC-REFERENCE-001"
        dataset.StudyDate = "20261001"
        dataset.SeriesNumber = 1
        dataset.InstanceNumber = 4 - index  # Intentionally opposes geometry order.
        dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        dataset.ImagePositionPatient = [0, 0, position]
        dataset.PixelSpacing = [0.5, 0.75]
        dataset.Rows = 4
        dataset.Columns = 4
        dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.BitsAllocated = 16
        dataset.BitsStored = 16
        dataset.HighBit = 15
        dataset.PixelRepresentation = 1
        dataset.RescaleSlope = 1
        dataset.RescaleIntercept = -1024
        dataset.WindowCenter = 40
        dataset.WindowWidth = 400
        pixels = (np.arange(16, dtype=np.int16).reshape(4, 4) + index * 100)
        dataset.PixelData = pixels.tobytes()
        path = output / f"synthetic-ct-{index:02d}.dcm"
        dataset.save_as(path, enforce_file_format=True)
        payload = path.read_bytes()
        files.append({
            "relative_path": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "sop_class_uid": str(CTImageStorage),
            "transfer_syntax_uid": str(ExplicitVRLittleEndian),
            "sop_instance_uid": str(dataset.SOPInstanceUID),
            "geometry_position_mm": position,
            "pixel_min": int(pixels.min()),
            "pixel_max": int(pixels.max()),
            "rescaled_min": int(pixels.min()) - 1024,
            "rescaled_max": int(pixels.max()) - 1024,
        })
    manifest = {
        "schema_version": "1.0",
        "fixture_id": "synthetic-ct-reference-v1",
        "source_name": "Voxura deterministic synthetic generator",
        "source_url": "backend/tools/build_synthetic_reference.py",
        "license": "Project-generated synthetic data; no external dataset or license",
        "license_reviewed_by": "not applicable: generated locally",
        "license_reviewed_at": "not applicable",
        "deidentification_reviewed_by": "not applicable: no source patient data",
        "retrieved_at": "not applicable",
        "dataset_version": "1",
        "case_identifier": "SYNTHETIC-REFERENCE-001",
        "allowed_use": "controlled non-clinical evaluation only",
        "clinical_data_root": False,
        "expected_order": [item["relative_path"] for item in files],
        "pixel_spacing_mm": [0.5, 0.75],
        "orientation_patient": [1, 0, 0, 0, 1, 0],
        "window_center": 40,
        "window_width": 400,
        "files": files,
        "notes": ["Synthetic technical reference only; clinical display approval is pending."],
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print(build(parser.parse_args().output))
