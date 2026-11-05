"""Offline release contract checks; never build/publish images from unittest."""
import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_legacy_compose_and_placeholder_scan_log_are_retired(self):
        self.assertFalse((ROOT / "docker-compose-old.yml").exists())
        self.assertFalse((ROOT / "mcp-shield.log").exists())
        archive = ROOT / "docs/archive/docker-compose-v1.yml.txt"
        self.assertTrue(archive.is_file())
        self.assertTrue(archive.read_text().startswith("RETIRED HISTORICAL TEXT — NOT A COMPOSE FILE."))

    def test_release_gate_refuses_an_existing_evidence_directory(self):
        result = subprocess.run(
            ["python3", str(ROOT / "tests/release_check.py"), "--image", "not-used",
             "--bridge-image", "not-used", "--output", str(ROOT / "tests")],
            text=True, capture_output=True, timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr.lower())

    def test_release_evidence_requires_all_cases_and_cleanup_not_just_status(self):
        spec = importlib.util.spec_from_file_location("release_check", ROOT / "tests/release_check.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        legacy = {"status": "passed", "cases": [{"status": "passed"}] * 4,
                  "startupRejections": [{"status": "passed", "exitCode": 1}] * 2,
                  "cleanup": [{"graceful": True, "oomKilled": False, "secretLeaked": False}] * 8,
                  "networkRemoved": True, "volumeRemoved": True}
        optional = {"status": "passed", "cases": [{"status": "passed"}] * 4,
                    "cleanup": [{"graceful": True, "oomKilled": False, "secretLeaked": False}] * 5,
                    "networkRemoved": True, "upstreamAuthFailure": {"status": "passed", "exitCode": 3}}
        self.assertTrue(module.evidence_passes(legacy, optional))
        for field, value in [("cases", []), ("cleanup", []), ("volumeRemoved", False)]:
            self.assertFalse(module.evidence_passes({**legacy, field: value}, optional))
        self.assertFalse(module.evidence_passes(legacy, {**optional, "upstreamAuthFailure": {"status": "passed", "exitCode": 0}}))

    def test_workflow_tests_loaded_images_before_registry_access_and_publication(self):
        workflow = (ROOT / ".github/workflows/docker-publish.yml").read_text()
        self.assertIn("tests/release_check.py", workflow)
        self.assertIn("load: true", workflow)
        self.assertNotIn("push: ${{ github.event_name != 'pull_request' }}", workflow)
        gate = workflow.index("tests/release_check.py")
        self.assertLess(gate, workflow.index("docker/login-action@"))
        self.assertLess(gate, workflow.index("docker push"))
        self.assertLess(gate, workflow.index("cosign sign"))


if __name__ == "__main__":
    unittest.main()
