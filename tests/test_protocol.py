"""Offline tests for smoke-client validation, not substitutes for real image calls."""
import io
import json
import queue
import unittest
from unittest.mock import patch

import integration_smoke as smoke


class ProtocolTests(unittest.TestCase):
    def test_sse_frames_preserve_multiline_data_and_ignore_comments(self):
        response = io.BytesIO(b": ping\n\nevent: endpoint\ndata: /message?sessionId=test\n\nevent: message\ndata: {\ndata: \"id\": 1}\n\n")
        self.assertEqual(list(smoke.sse_events(response)), [
            ("endpoint", "/message?sessionId=test"), ("message", '{\n"id": 1}'),
        ])

    def test_sse_frame_is_not_dispatched_without_terminating_blank_line(self):
        self.assertEqual(list(smoke.sse_events(io.BytesIO(b"data: incomplete"))), [])

    def test_oversized_sse_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "1 MiB"):
            list(smoke.sse_events(io.BytesIO(b"data: " + b"x" * 1_048_576 + b"\n\n")))

    def test_message_endpoint_stays_on_the_selected_loopback_connection(self):
        for value in ["/message?sessionId=test", "http://localhost:8081/message?sessionId=test",
                      "http://127.0.0.1:30123/message?sessionId=test"]:
            self.assertEqual(smoke.message_path(value, 30123), "/message?sessionId=test")
        for value in ["https://example.com/message", "//example.com/message", "http://localhost:1234/message",
                      "http://user@localhost:8081/message", "/other", "/message#fragment"]:
            with self.subTest(endpoint=value), self.assertRaises(AssertionError):
                smoke.message_path(value, 30123)

    def client(self, responses):
        client = smoke.SseClient.__new__(smoke.SseClient)
        client.sequence, client.timeout, client.messages = 0, 1, queue.Queue()
        client.send = lambda payload: [client.messages.put(response) for response in responses]
        return client

    def test_rpc_requires_matching_completed_result_not_an_ack_or_notification(self):
        client = self.client([
            ("message", json.dumps({"jsonrpc": "2.0", "method": "notifications/message"})),
            ("message", json.dumps({"jsonrpc": "2.0", "id": 999, "result": "wrong"})),
            ("message", json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})),
        ])
        self.assertEqual(client.rpc("tools/list"), {"tools": []})
        with self.assertRaises(queue.Empty):
            self.client([]).rpc("tools/list")

    def test_rpc_error_and_disconnect_are_failures(self):
        for response in [("closed", "stream ended"), ("message", json.dumps({"id": 1, "error": {"code": -32602}}))]:
            with self.subTest(response=response), self.assertRaises(AssertionError):
                self.client([response]).rpc("tools/call")

    def test_cleanup_refuses_a_container_without_its_ownership_label(self):
        runner = smoke.Smoke.__new__(smoke.Smoke)
        runner.run_id = "owned-run"
        with patch.object(smoke, "docker", return_value="different-run") as command:
            with self.assertRaisesRegex(AssertionError, "ownership"):
                runner.stop("synthetic-container-id", "everything")
            self.assertEqual(command.call_count, 1)
            self.assertEqual(command.call_args.args[0], "inspect")

    def test_failed_fixture_shutdown_cannot_produce_overall_pass(self):
        runner = smoke.Smoke.__new__(smoke.Smoke)
        runner.run_id, runner.prefix, runner.network = "owned-run", "synthetic", None
        runner.catalog, runner.containers = {"servers": []}, []
        runner.report = {"cases": [{"status": "passed"}], "cleanup": [], "status": "incomplete"}
        runner.write = lambda: None
        runner.startup_rejections = lambda: None
        runner.container = lambda *args, **kwargs: runner.containers.append(("fixture-id", "fixture"))

        def stopped(*args):
            runner.report["cleanup"].append({"graceful": False})
            runner.containers.clear()

        runner.stop = stopped
        def command(*args):
            return "owned-run" if "inspect" in args else "synthetic-resource-id"

        with patch.object(smoke, "docker", side_effect=command):
            self.assertEqual(runner.run()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
