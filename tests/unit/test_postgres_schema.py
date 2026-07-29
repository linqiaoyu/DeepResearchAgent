from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "generate_postgres_schema", ROOT / "scripts" / "generate_postgres_schema.py"
)
assert SPEC and SPEC.loader
schema_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schema_script)


class PostgresSchemaTests(unittest.TestCase):
    def test_checked_in_schema_is_generated_from_migrations(self) -> None:
        self.assertEqual(
            (ROOT / "docs" / "postgres_schema.sql").read_text(encoding="utf-8"),
            schema_script.rendered_schema(),
        )


if __name__ == "__main__":
    unittest.main()
