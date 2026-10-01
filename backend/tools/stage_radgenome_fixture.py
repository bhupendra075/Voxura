"""Stage an already-approved RadGenome fixture for offline research evaluation.

This command intentionally does not download data, weights, or reports. It is
not connected to the clinical API or clinical object store.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from research.preflight import ResearchFixtureError, load_fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a licensed RadGenome research fixture")
    parser.add_argument("--manifest", type=Path, required=True, help="Approved fixture manifest JSON")
    parser.add_argument("--accept-upstream-terms", action="store_true", help="Confirms the operator reviewed the upstream dataset/model terms")
    args = parser.parse_args()
    if not args.accept_upstream_terms:
        parser.error("Refusing to stage public data until --accept-upstream-terms is provided")
    clinical_root = Path(os.environ.get("CLINICAL_DATA_ROOT", Path(__file__).parents[1] / "clinical_data"))
    try:
        fixture = load_fixture(args.manifest, clinical_root)
    except (OSError, ValueError, json.JSONDecodeError, ResearchFixtureError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        "state": "ready_for_offline_research_only",
        "source": fixture.payload["source"],
        "case_id": fixture.payload["case_id"],
        "split": fixture.payload["split"],
        "mode": fixture.mode,
        "clinical_import": "forbidden",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
