from __future__ import annotations

import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_ROOT = Path(tempfile.mkdtemp(prefix="feeddock-tests-"))
os.environ["TESTING"] = "true"
os.environ["DATA_DIR"] = str(TEST_ROOT)
os.environ["DATABASE_PATH"] = str(TEST_ROOT / "feeddock.db")
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "password"
os.environ["APP_VERSION"] = "1.8.0-test"
