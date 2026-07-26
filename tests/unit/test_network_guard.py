from __future__ import annotations

import socket
import unittest

from tests.unit.network_guard import allow_network


class UnitNetworkGuardTests(unittest.TestCase):
    def test_external_connection_is_rejected_with_actionable_message(self) -> None:
        with socket.socket() as sock:
            with self.assertRaisesRegex(
                AssertionError,
                "unit test attempted network egress; use @allow_network",
            ):
                sock.connect(("198.51.100.1", 443))

    @allow_network
    def test_opt_out_marker_is_explicit(self) -> None:
        self.assertTrue(getattr(self.test_opt_out_marker_is_explicit, "_deepresearch_allow_network"))
