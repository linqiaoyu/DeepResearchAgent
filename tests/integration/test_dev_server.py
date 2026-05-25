from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class DevServerTests(unittest.TestCase):
    def test_get_research_returns_checkpointed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_path = Path(tmp) / "research.db"
            original_storage_path = os.environ.get("DEEPRESEARCH_STORAGE_PATH")
            os.environ["DEEPRESEARCH_STORAGE_PATH"] = str(storage_path)
            try:
                dev_server = importlib.import_module("scripts.dev_server")
            finally:
                if original_storage_path is None:
                    os.environ.pop("DEEPRESEARCH_STORAGE_PATH", None)
                else:
                    os.environ["DEEPRESEARCH_STORAGE_PATH"] = original_storage_path

            engine = DeepResearchEngine(settings=Settings(storage_path=storage_path, max_critic_iter=1))
            state = engine.run(topic="fallback checkpoint contract", depth_level=1)

            self.assertEqual(
                dev_server.research_state_path_id(f"/research/{state.research_id}"),
                state.research_id,
            )
            self.assertIsNone(dev_server.research_state_path_id(f"/research/{state.research_id}/report"))

            payload, status = dev_server.research_state_response(engine, state.research_id)

            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(payload["research_id"], state.research_id)
            self.assertEqual(payload["topic"], "fallback checkpoint contract")
            self.assertIn("current_phase", payload)
            self.assertIn("status", payload)

            missing_payload, missing_status = dev_server.research_state_response(engine, "does-not-exist")
            self.assertEqual(missing_status, HTTPStatus.NOT_FOUND)
            self.assertEqual(missing_payload, {"error": "research_id not found"})
            json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
