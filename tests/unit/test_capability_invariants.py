"""R109: a capability that is on and inert must not pass configuration.

`RESEARCH_LOOP_ENABLED` is documented in the AGENTS.md flag table as a
content-affecting capability. Every guard reads `Settings.research_loop_active`,
which also requires `research_loop_max_iterations > 1`, and that setting
defaults to 1. Turning the documented flag on therefore changed nothing, and
nothing said so.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from deepresearch_agent.config_validation import (
    ConfigurationInvariantError,
    validate_capability_invariants,
)
from deepresearch_agent.settings import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(storage_path=Path("/tmp/r109.db"), **overrides)


class CapabilityInvariantTests(unittest.TestCase):
    def test_the_loop_switched_on_at_one_iteration_is_refused(self) -> None:
        with self.assertRaises(ConfigurationInvariantError) as caught:
            validate_capability_invariants(_settings(research_loop_enabled=True))

        self.assertIn("RESEARCH_LOOP_ENABLED", str(caught.exception))
        self.assertIn("MAX_ITERATIONS", str(caught.exception))

    def test_the_loop_switched_on_with_iterations_is_accepted(self) -> None:
        settings = _settings(
            research_loop_enabled=True, research_loop_max_iterations=3
        )

        validate_capability_invariants(settings)

        self.assertTrue(settings.research_loop_active)

    def test_the_default_configuration_is_accepted(self) -> None:
        validate_capability_invariants(_settings())

    def test_the_refusal_names_the_value_it_saw(self) -> None:
        """An operator must not have to guess which setting was wrong."""
        with self.assertRaises(ConfigurationInvariantError) as caught:
            validate_capability_invariants(
                _settings(research_loop_enabled=True, research_loop_max_iterations=1)
            )

        self.assertIn("got 1", str(caught.exception))

    def test_the_documented_flag_alone_can_never_be_silently_inert(self) -> None:
        """The property, stated directly: on and inert is not a valid state."""
        settings = _settings(research_loop_enabled=True)

        self.assertFalse(settings.research_loop_active)
        with self.assertRaises(ConfigurationInvariantError):
            validate_capability_invariants(settings)


if __name__ == "__main__":
    unittest.main()
