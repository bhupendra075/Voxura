from __future__ import annotations

import atexit
import os
import shutil
import tempfile


_test_data_root = tempfile.mkdtemp(prefix="medscope-tests-")
os.environ["CLINICAL_DATA_ROOT"] = _test_data_root
os.environ.pop("CLINICAL_DATABASE_URL", None)
os.environ["CLINICAL_ENV"] = "test"
os.environ["CLINICAL_DEV_MODE"] = "1"
os.environ["CLINICAL_JWT_SECRET"] = "test-only-secret-not-for-production"

atexit.register(shutil.rmtree, _test_data_root, True)
