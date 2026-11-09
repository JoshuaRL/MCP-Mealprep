"""Offline launcher tests: no npm/uv downloads, containers or provider credentials."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
STUB = r'''
import json, os, signal, subprocess, sys
from pathlib import Path

args = sys.argv[1:]
runner = Path(sys.argv[0]).name
gateway = runner == "supergateway" or (runner == "npx" and args[:2] == ["-y", "supergateway"])
with open(os.environ["TRACE_FILE"], "a") as output:
    output.write(json.dumps({"kind": "gateway" if gateway else "backend", "runner": runner, "args": args, "pid": os.getpid(), "provider": os.environ.get("SUPABASE_ACCESS_TOKEN")}) + "\n")
if gateway:
    command = args[args.index("--stdio") + 1]
    result = subprocess.run(["/bin/sh", "-c", command], env=os.environ)
    if result.returncode:
        sys.exit(result.returncode)
    if os.environ.get("MOCK_GATEWAY_WAIT") == "true":
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        with open(os.environ["READY_FILE"], "w") as output:
            output.write("ready")
        signal.pause()
    sys.exit(int(os.environ.get("MOCK_GATEWAY_EXIT", "0")))
'''


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mealprep-launcher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "trace.jsonl"
        self.ready = self.root / "ready"
        self.key = self.root / "gateway-key"
        self.key.write_text("synthetic-gateway-key\n")
        for name in ["npx", "uvx", "uv", "python3", "supergateway"]:
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n" + STUB)
            path.chmod(0o755)

    def env(self, **options):
        return {
            "PATH": str(self.bin) + ":/usr/bin:/bin",
            "HOME": str(self.root),
            "TMPDIR": str(self.root),
            "TRACE_FILE": str(self.trace),
            "READY_FILE": str(self.ready),
            "MCP_COMMAND_TYPE": "npx",
            "MCP_PACKAGE": "fixture-server",
            "MCP_API_KEY_FILE": str(self.key),
            **options,
        }

    def launch(self, **options):
        return subprocess.run(
            ["/bin/bash", str(ROOT / "startup.sh")], cwd=self.root,
            env=self.env(**options), text=True, capture_output=True, timeout=5,
        )

    def events(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()] if self.trace.exists() else []

    def assert_rejected(self, **options):
        result = self.launch(**options)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events(), [], result.stdout + result.stderr)
        return result

    def test_script_parses(self):
        result = subprocess.run(["bash", "-n", str(ROOT / "startup.sh")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gateway_secret_is_required_and_invalid_files_fail_closed(self):
        for path in ["", str(self.root / "missing"), str(self.root)]:
            self.assert_rejected(MCP_API_KEY_FILE=path)
        for content in ["", "  \n", "short", "valid-key-with-enough-characters\nsecond-key-with-enough-characters"]:
            self.key.write_text(content)
            self.assert_rejected()

    def test_gateway_only_receives_key_path_and_quiet_logging(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.events()[0]["args"]
        self.assertEqual(args[args.index("--apiKeyFile") + 1], str(self.key))
        self.assertEqual(args[args.index("--logLevel") + 1], "none")
        self.assertNotIn("synthetic-gateway-key", result.stdout + result.stderr + json.dumps(self.events()))

    def test_additional_gateway_credential_sources_are_rejected(self):
        self.assert_rejected(SUPERGATEWAY_API_KEY="synthetic-extra-key")
        self.assert_rejected(SUPERGATEWAY_API_KEY_FILE=str(self.key))

    def test_provider_file_is_loaded_without_logging_and_conflicts_fail(self):
        secret = self.root / "provider"
        secret.write_text("synthetic-provider-token\n")
        result = self.launch(SUPABASE_ACCESS_TOKEN_FILE=str(secret))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events()[1]["provider"], "synthetic-provider-token")
        self.assertNotIn("synthetic-provider-token", result.stdout + result.stderr)
        self.trace.unlink()
        self.assert_rejected(SUPABASE_ACCESS_TOKEN_FILE=str(secret), SUPABASE_ACCESS_TOKEN="conflict")
        self.assert_rejected(SUPABASE_ACCESS_TOKEN_FILE=str(self.root / "missing"))
        for content in ["", " \n", "first\nsecond", "value\r\n"]:
            secret.write_text(content)
            self.assert_rejected(SUPABASE_ACCESS_TOKEN_FILE=str(secret))

    def test_missing_package_never_falls_back_to_everything(self):
        env = self.env()
        del env["MCP_PACKAGE"]
        result = subprocess.run(["bash", str(ROOT / "startup.sh")], cwd=self.root, env=env, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events(), [])

    def test_empty_package_is_rejected(self):
        self.assert_rejected(MCP_PACKAGE="")

    def test_whitespace_only_package_is_rejected(self):
        self.assert_rejected(MCP_PACKAGE=" \t ")

    def test_empty_runner_is_rejected(self):
        self.assert_rejected(MCP_COMMAND_TYPE="")

    def test_missing_runner_is_rejected(self):
        env = self.env()
        del env["MCP_COMMAND_TYPE"]
        result = subprocess.run(["bash", str(ROOT / "startup.sh")], cwd=self.root, env=env, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events(), [])

    def test_unknown_runner_is_rejected(self):
        self.assert_rejected(MCP_COMMAND_TYPE="unknown")

    def test_invalid_port_is_rejected_before_launch(self):
        for port in ["0", "65536", "-1", "8081junk", "999999999999999999999"]:
            with self.subTest(port=port):
                self.assert_rejected(MCP_PORT=port)

    def test_port_boundaries_and_decimal_normalization(self):
        for port, expected in [("1", "1"), ("65535", "65535"), ("08081", "8081")]:
            with self.subTest(port=port):
                self.trace.unlink(missing_ok=True)
                result = self.launch(MCP_PORT=port)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = self.events()[0]["args"]
                self.assertEqual(args[args.index("--port") + 1], expected)

    def test_gateway_owns_backend_without_prelaunch_or_scanner(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self.events()
        self.assertEqual([event["kind"] for event in events], ["gateway", "backend"])
        self.assertEqual(events[1]["args"], ["-y", "fixture-server"])

    def test_gateway_uses_installed_binary_without_an_npm_wrapper(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events()[0]["runner"], "supergateway")

    def test_default_streamable_http_and_explicit_legacy_sse(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.events()[0]["args"]
        self.assertIn("--stateful", args)
        self.assertEqual(args[args.index("--outputTransport") + 1], "streamableHttp")
        self.assertEqual(args[args.index("--streamableHttpPath") + 1], "/mcp")
        self.trace.unlink()
        result = self.launch(MCP_TRANSPORT="sse")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.events()[0]["args"]
        self.assertEqual(args[args.index("--outputTransport") + 1], "sse")
        self.assertNotIn("--stateful", args)

    def test_unknown_transport_fails_before_launch(self):
        self.assert_rejected(MCP_TRANSPORT="invalid")

    def test_runners_have_valid_explicit_argv(self):
        for runner, expected in [("npx", ["-y", "fixture-server"]), ("uvx", ["fixture-server"]),
                                 ("uv", ["tool", "run", "fixture-server"]), ("python3", ["-m", "fixture_server"])]:
            with self.subTest(runner=runner):
                self.trace.unlink(missing_ok=True)
                package = "fixture_server" if runner == "python3" else "fixture-server"
                result = self.launch(MCP_COMMAND_TYPE=runner, MCP_PACKAGE=package)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.events()[1]["runner"], runner)
                self.assertEqual(self.events()[1]["args"], expected)

    def test_package_is_one_literal_argument_not_shell_code(self):
        package = "fixture name; echo literal '$HOME'"
        result = self.launch(MCP_PACKAGE=package)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events()[1]["args"], ["-y", package])
        self.assertNotIn("literal", result.stdout)

    def test_legacy_shell_arguments_keep_quoted_words(self):
        result = self.launch(MCP_ARGS='--label "two words" --path "/tmp/space path"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events()[1]["args"], ["-y", "fixture-server", "--label", "two words", "--path", "/tmp/space path"])

    def test_gateway_exit_status_is_preserved(self):
        result = self.launch(MOCK_GATEWAY_EXIT="17")
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual([event["kind"] for event in self.events()], ["gateway", "backend"])

    def test_mcpo_fails_explicitly_until_its_separate_repair(self):
        result = self.assert_rejected(USE_MCPO="true")
        self.assertIn("mcpo", result.stderr.lower())
        self.assertIn("docker-compose.mcpo.yml", result.stderr)

    def test_invalid_mcpo_flag_is_rejected(self):
        self.assert_rejected(USE_MCPO="treu")

    def test_legacy_superargs_flag_does_not_prelaunch_backend(self):
        result = self.launch(USE_SUPERARGS="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([event["kind"] for event in self.events()], ["gateway", "backend"])

    def test_foreground_pid_and_sigterm_reach_gateway(self):
        process = subprocess.Popen(
            ["/bin/bash", str(ROOT / "startup.sh")], cwd=self.root,
            env=self.env(MOCK_GATEWAY_WAIT="true"), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 3
            while not self.ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.ready.exists(), "Controlled gateway did not become ready")
            gateway = next(event for event in self.events() if event["kind"] == "gateway")
            self.assertEqual(gateway["pid"], process.pid, "Launcher must exec, not leave Bash as parent")
            process.terminate()
            self.assertEqual(process.wait(timeout=3), 143)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is required for recipe validation")
class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["docker", "compose", "--env-file", "/dev/null", "-f", str(ROOT / "docker-compose.yml"), "config", "--format", "json"],
            text=True, capture_output=True, timeout=30,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp")},
        )
        if result.returncode:
            raise AssertionError("Compose configuration validation failed: " + result.stderr)
        cls.services = json.loads(result.stdout)["services"]

    def test_optional_bridge_uses_separate_target_port_keys_and_readiness(self):
        result = subprocess.run(
            ["docker", "compose", "--env-file", "/dev/null", "-f", str(ROOT / "docker-compose.yml"),
             "-f", str(ROOT / "docker-compose.mcpo.yml"), "config", "--format", "json"],
            text=True, capture_output=True, timeout=30,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp")},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        service = config["services"]["mcp-mealprep-mcpo"]
        self.assertEqual(service["build"]["target"], "mcpo")
        self.assertNotEqual(service["image"], self.services["mcp-mealprep-everything"]["image"])
        self.assertEqual(service["user"], "1000:1000")
        self.assertEqual(service["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(service["ports"][0]["target"], 8000)
        self.assertNotEqual(service["environment"]["MCPO_API_KEY_FILE"], service["environment"]["MCP_API_KEY_FILE"])
        self.assertEqual(service["environment"]["MCPO_UPSTREAM_URL"], "http://mcp-mealprep-everything:8081/mcp")
        self.assertEqual(service["depends_on"]["mcp-mealprep-everything"]["condition"], "service_healthy")

    def test_every_recipe_selects_its_intended_package_and_runner(self):
        expected = {
            "everything": ("npx", "@modelcontextprotocol/server-everything"),
            "fetch": ("uvx", "mcp-server-fetch"),
            "supabase": ("npx", "@supabase/mcp-server-supabase"),
            "sequential-thinking": ("npx", "@modelcontextprotocol/server-sequential-thinking"),
            "calculator": ("uvx", "mcp-server-calculator"),
            "memory": ("npx", "@modelcontextprotocol/server-memory"),
            "puppeteer": ("npx", "@modelcontextprotocol/server-puppeteer"),
            "searxng": ("npx", "mcp-searxng@2.10.0"),
            "slack": ("npx", "@modelcontextprotocol/server-slack"),
            "everart": ("npx", "@modelcontextprotocol/server-everart"),
            "gmaps": ("npx", "@modelcontextprotocol/server-google-maps"),
            "brave-search": ("npx", "@modelcontextprotocol/server-brave-search"),
            "aws-kb-retrieval": ("uvx", "mcp-server-aws-kb-retrieval"),
            "docker": ("uvx", "mcp-server-docker"),
        }
        # baserow is a standalone read-only example service, not a gateway
        # recipe: no MCP_PACKAGE/startup.sh contract applies to it.
        self.assertEqual(set(self.services),
                         {"mcp-mealprep-" + name for name in expected} | {"mcp-mealprep-baserow"})
        for name, (runner, package) in expected.items():
            with self.subTest(service=name):
                env = self.services["mcp-mealprep-" + name]["environment"]
                self.assertEqual(env.get("MCP_COMMAND_TYPE"), runner)
                self.assertEqual(env.get("MCP_PACKAGE"), package)

    def test_supabase_uses_the_cli_credential_and_project_options(self):
        env = self.services["mcp-mealprep-supabase"]["environment"]
        self.assertIn("SUPABASE_ACCESS_TOKEN_FILE", env)
        self.assertIn("--read-only", env.get("MCP_ARGS", ""))
        self.assertIn("--project-ref", env.get("MCP_ARGS", ""))
        self.assertNotIn("MCP_SUPABASE_DB_PASSWORD", env)

    def test_hardened_defaults_and_pull_selection(self):
        for name, service in self.services.items():
            self.assertEqual(service["user"], "1000:1000")
            self.assertIn("ALL", service["cap_drop"])
            self.assertIn("no-new-privileges:true", service["security_opt"])
            self.assertIn("ghcr.io/joshuarl/mcp-mealprep", service["image"])
            self.assertEqual(service["pull_policy"], "always")
            self.assertNotIn("build", service)
            self.assertTrue(service["secrets"])
            for port in service["ports"]:
                self.assertEqual(port["host_ip"], "127.0.0.1")
            if name == "mcp-mealprep-baserow":
                # Standalone read-only example: no gateway key/startup.sh.
                self.assertNotIn("MCP_API_KEY_FILE", service.get("environment", {}))
                self.assertFalse(service.get("command"))
                continue
            self.assertTrue(service["environment"]["MCP_API_KEY_FILE"].startswith("/run/secrets/"))
        memory = self.services["mcp-mealprep-memory"]
        self.assertEqual(memory["environment"]["MEMORY_FILE_PATH"], "/data/memory/memory.jsonl")
        self.assertTrue(any(v["type"] == "volume" and v["target"] == "/data/memory" for v in memory["volumes"]))


if __name__ == "__main__":
    unittest.main()
