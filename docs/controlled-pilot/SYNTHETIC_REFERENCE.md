# Synthetic technical reference

Generate the local, ignored fixture with:

```powershell
cd backend
..\.venv-test\Scripts\python.exe tools\build_synthetic_reference.py evaluation_data\synthetic-reference
```

`manifest.json` records provenance, SHA-256, byte count, SOP class, transfer syntax, expected pixel range, rescale values, geometry order, orientation, spacing, and window values for three synthetic CT instances. Generation uses fixed UIDs and pixels and needs no external data, download, or license. Repeating generation must produce the same manifest hash.

The `test_synthetic_reference.py` integration test re-hashes each source, checks the pixel range, imports in reverse order, checks geometry ordering and measurement calibration, then retrieves each stored DICOM to confirm byte equality. This is a technical reference. It does not establish approved clinical display parity or satisfy the formal display gate; reviewer approval, reference images, and tolerances remain required.
