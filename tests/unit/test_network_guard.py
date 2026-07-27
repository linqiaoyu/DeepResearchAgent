from __future__ import annotations

import socket
import threading
import unittest

from tests.unit import network_guard
from tests.unit.network_guard import allow_network, run_with_network_context


class UnitNetworkGuardTests(unittest.TestCase):
    def test_external_connection_is_rejected_with_actionable_message(self) -> None:
        with socket.socket() as sock:
            with self.assertRaisesRegex(
                AssertionError,
                "test attempted network egress; use @allow_network",
            ):
                sock.connect(("198.51.100.1", 443))

    def test_external_connection_ex_is_rejected(self) -> None:
        with socket.socket() as sock:
            with self.assertRaisesRegex(AssertionError, "test attempted network egress"):
                sock.connect_ex(("198.51.100.1", 443))

    @allow_network
    def test_opt_out_marker_is_explicit(self) -> None:
        self.assertTrue(getattr(self.test_opt_out_marker_is_explicit, "_deepresearch_allow_network"))

    @allow_network
    def test_opt_out_context_can_be_propagated_to_worker_thread(self) -> None:
        outcome: list[BaseException | None] = []
        original_connect = network_guard._ORIGINAL_CONNECT

        def recorded_connect(_sock: socket.socket, _address: object) -> None:
            return None

        def connect() -> None:
            try:
                with socket.socket() as sock:
                    sock.connect(("198.51.100.1", 9))
            except BaseException as exc:
                outcome.append(exc)
            else:
                outcome.append(None)

        network_guard._ORIGINAL_CONNECT = recorded_connect
        try:
            worker = threading.Thread(target=run_with_network_context(connect))
            worker.start()
            worker.join(timeout=1)
        finally:
            network_guard._ORIGINAL_CONNECT = original_connect
        self.assertFalse(worker.is_alive())
        self.assertFalse(any(isinstance(item, AssertionError) for item in outcome))
