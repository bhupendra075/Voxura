# Research-only public fixture gate

This package protects the boundary between public engineering data and clinical data.
It does not download RadGenome-Brain MRI, model weights, or reports; a data custodian must review and accept the upstream terms first.

Start from `radgenome.manifest.example.json`, populate it only with files obtained under those terms, calculate their SHA-256 values, set `license_reviewed` to `true`, and run `tools/stage_radgenome_fixture.py --manifest <path> --accept-upstream-terms`. The command only validates and stages an offline research case; it never uploads, imports, or displays it in the clinical worklist.

Create a manifest outside `clinical_data`, verify all artifact checksums, then call `load_fixture`. The caller may run a pinned offline model in `given-mask` or `predicted-mask` mode and pass only structured, non-clinical evaluation results to `write_run_record`.

Every output record is write-once and includes the case/split, model checksum, preprocessing version, and mode. It must never be imported through `/v3/import` or attached to a clinical worklist.
