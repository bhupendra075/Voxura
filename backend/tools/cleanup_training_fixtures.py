"""Review and optionally remove test-created TRAINING^PATIENT studies.

Dry-run is the default. Pass --apply only after reviewing the printed study IDs.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="delete the listed fixtures and their stored objects")
    args = parser.parse_args()
    root = Path(os.getenv("CLINICAL_DATA_ROOT", Path(__file__).parents[1] / "clinical_data")).resolve()
    database = root / "clinical.db"
    if not database.exists():
        print(f"No development database exists at {database}")
        return 0
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT id,patient_id,accession,study_date FROM studies WHERE patient_name=? AND patient_id LIKE ?",
        ("TRAINING^PATIENT", "TRAIN-%"),
    ).fetchall()
    print(f"Found {len(rows)} exact training fixture(s):")
    for row in rows:
        print(f"  {row['id']}  {row['patient_id']}  {row['accession']}  {row['study_date']}")
    if not args.apply or not rows:
        print("Dry run only; no data was changed.")
        connection.close()
        return 0
    for row in rows:
        study_id = row["id"]
        paths = [Path(item[0]).resolve() for item in connection.execute(
            "SELECT i.object_path FROM instances i JOIN series s ON s.id=i.series_id WHERE s.study_id=?", (study_id,)
        ).fetchall()]
        connection.execute("DELETE FROM presentation_states WHERE study_id=?", (study_id,))
        connection.execute("DELETE FROM reports WHERE study_id=?", (study_id,))
        connection.execute("DELETE FROM instances WHERE series_id IN (SELECT id FROM series WHERE study_id=?)", (study_id,))
        connection.execute("DELETE FROM series WHERE study_id=?", (study_id,))
        connection.execute("DELETE FROM studies WHERE id=?", (study_id,))
        for path in paths:
            if root in path.parents and path.is_file():
                path.unlink()
    connection.commit()
    connection.close()
    print(f"Removed {len(rows)} reviewed training fixture(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
