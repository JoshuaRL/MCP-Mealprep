"""Offline public-entrypoint tests; mcpo itself is tested in a real image."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mealprep-bridge-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        package = self.root / "mcpo"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "main.py").write_text('import json, os\nasync def run(**kwargs):\n print(json.dumps({**kwargs, "logLevel": os.environ.get("LOG_LEVEL")}))\n')
        self.inbound = self.root / "inbound"
        self.upstream = self.root / "upstream"
        self.inbound.write_text("synthetic-bridge-key-for-tests\n")
        self.upstream.write_text("synthetic-gateway-key-for-tests\n")

    def launch(self, **options):
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(self.root),
               "MCPO_API_KEY_FILE": str(self.inbound), "MCP_API_KEY_FILE": str(self.upstream),
               "MCPO_UPSTREAM_URL": "http://gateway:8081/mcp", **options}
        return subprocess.run([sys.executable, str(ROOT / "mcpo_bridge.py")], env=env,
                              text=True, capture_output=True, timeout=5)

    def test_bridge_passes_secrets_in_memory_with_strict_auth_and_remote_upstream(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertTrue(settings["strict_auth"])
        self.assertEqual(settings["api_key"], self.inbound.read_text().strip())
        self.assertEqual(settings["headers"], {"Authorization": "Bearer " + self.upstream.read_text().strip()})
        self.assertEqual(settings["server_type"], "streamable-http")
        self.assertEqual(settings["server_command"], ["http://gateway:8081/mcp"])
        self.assertEqual(settings["port"], 8000)
        self.assertEqual(settings["logLevel"], "WARNING")
        self.assertNotIn("*", settings["cors_allow_origins"])

    def test_missing_invalid_and_reused_keys_fail_before_mcpo(self):
        for options in [{"MCPO_API_KEY_FILE": ""}, {"MCP_API_KEY_FILE": "/missing"},
                        {"MCPO_API_KEY_FILE": str(self.upstream)}]:
            result = self.launch(**options)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
        for content in ["", "short", "first-valid-length-key\nsecond-valid-length-key"]:
            self.inbound.write_text(content)
            result = self.launch()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_invalid_ports_and_unsafe_urls_fail_without_disclosing_credentials(self):
        for options in [{"MCPO_PORT": "0"}, {"MCPO_PORT": "65536"}, {"MCPO_PORT": "oops"},
                        {"MCPO_UPSTREAM_URL": "http://user:synthetic-url-secret@gateway/mcp"},
                        {"MCPO_UPSTREAM_URL": "http://gateway/mcp?key=synthetic-url-secret"},
                        {"MCPO_UPSTREAM_URL": "file:///mcp"}]:
            result = self.launch(**options)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("synthetic-url-secret", result.stderr)

    def test_wildcard_and_invalid_cors_origins_fail_closed(self):
        for origin in ["*", "", "http://localhost:3000/", "http://user:password@localhost:3000"]:
            result = self.launch(MCPO_ALLOWED_ORIGIN=origin)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
