"""Offline regression gates for the bounded Streamable HTTP smoke client."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from integration_optional import HttpClient


class OptionalClientTests(unittest.TestCase):
    def test_http_rpc_needs_matching_completed_result(self):
        client = HttpClient(12345)
        for result in [(200, {"id": 999, "result": {}}), (202, None),
                       (200, {"id": 1, "error": {"code": -32600}})]:
            client.sequence = 0
            client.request = Mock(return_value=result)
            with self.subTest(result=result), self.assertRaises(AssertionError):
                client.rpc("tools/list")
        client.sequence = 0
        client.request = Mock(return_value=(200, {"id": 1, "result": {"tools": []}}))
        self.assertEqual(client.rpc("tools/list"), {"tools": []})

    def test_session_delete_must_make_session_unusable(self):
        client = HttpClient(12345)
        client.session = "synthetic-session"
        client.request = Mock(side_effect=[(200, None), (200, {"result": {}})])
        with self.assertRaisesRegex(AssertionError, "remained usable"):
            client.close()
        client.request = Mock(side_effect=[(200, None), (404, {})])
        client.close()
        self.assertIsNone(client.session)

    def test_http_sse_ignores_unmatched_ids_and_uses_configured_file_key(self):
        response = io.BytesIO(b'data: {"id":999,"result":{}}\n\ndata: {"id":1,"result":{"ok":true}}\n\n')
        response.status = 200
        response.getheader = lambda key, default=None: {"Content-Type": "text/event-stream", "Mcp-Session-Id": "synthetic-session"}.get(key, default)
        connection = Mock()
        connection.getresponse.return_value = response
        client = HttpClient(12345, key="synthetic-custom-key-from-file")
        with patch("integration_optional.http.client.HTTPConnection", return_value=connection):
            self.assertEqual(client.rpc("ping"), {"ok": True})
        headers = connection.request.call_args.args[3]
        self.assertEqual(headers["Authorization"], "Bearer synthetic-custom-key-from-file")
        self.assertEqual(client.session, "synthetic-session")
        connection.close.assert_called_once()

    def test_client_json_examples_have_only_placeholder_credentials(self):
        from integration_optional import ROOT
        example = json.loads((ROOT / "examples/opencode-v2.json").read_text())
        server = example["mcp"]["servers"]["mealprep"]
        self.assertEqual(server["type"], "remote")
        self.assertFalse(server["oauth"])
        self.assertEqual(server["protocol"], "legacy")
        self.assertEqual(server["headers"]["Authorization"], "Bearer {env:MEALPREP_GATEWAY_KEY}")
        for file, value in [("cursor.json", "Bearer ${env:MEALPREP_GATEWAY_KEY}"),
                            ("claude-code.json", "Bearer ${MEALPREP_GATEWAY_KEY}")]:
            server = json.loads((ROOT / "examples" / file).read_text())["mcpServers"]["mealprep"]
            self.assertEqual(server["headers"]["Authorization"], value)
            self.assertTrue(server["url"].endswith("/mcp"))


if __name__ == "__main__":
    unittest.main()
