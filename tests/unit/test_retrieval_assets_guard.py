from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.require_retrieval_assets import require_retrieval_assets


class RetrievalAssetsGuardTests(unittest.TestCase):
    def test_missing_database_fails_closed_with_path(self) -> None:
        missing = Path(tempfile.mkdtemp()) / "missing.db"
        with self.assertRaisesRegex(FileNotFoundError, str(missing)):
            require_retrieval_assets(missing)


if __name__ == "__main__":
    unittest.main()
