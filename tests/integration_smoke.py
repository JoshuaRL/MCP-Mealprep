"""Explicit real-image smoke. Not run by unittest; never publishes or uses credentials."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import queue
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[1]
LABEL = "mealprep.smoke.run"
MARKER = "synthetic-mealprep-fixture"
SYNTHETIC_KEY = "synthetic-mealprep-gateway-key-not-for-deployment"
FIXTURE = '''
from http.server import BaseHTTPRequestHandler, HTTPServer
import signal, sys
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"User-agent: *\\nAllow: /\\n" if self.path == "/robots.txt" else b"synthetic-mealprep-fixture"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
'''


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sse_events(response):
    """Parse bounded SSE frames, not HTTP success as a proxy for MCP completion."""
    event, data, size = "message", [], 0
    while True:
        raw = response.readline(1_048_577)
        if not raw:
            return
        size += len(raw)
        require(size <= 1_048_576, "SSE frame exceeded 1 MiB")
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data, size = "message", [], 0
        elif line.startswith("event:"):
            event = line[6:].lstrip(" ")
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)


def message_path(endpoint, port):
    parsed = urlsplit(endpoint)
    require(not parsed.username and not parsed.password and not parsed.fragment, "Unsafe SSE endpoint")
    if parsed.scheme or parsed.netloc:
        require(parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
                and parsed.port in {port, 8081}, "Off-origin SSE endpoint refused")
    require(parsed.path == "/message", "Unexpected message endpoint")
    return parsed.path + ("?" + parsed.query if parsed.query else "")


class SseClient:
    def __init__(self, port, timeout=120, key=SYNTHETIC_KEY):
        self.port, self.timeout, self.sequence = port, timeout, 0
        self.headers = {"Authorization": "Bearer " + key}
        self.messages = queue.Queue()
        deadline = time.monotonic() + timeout
        while True:
            self.connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                self.connection.request("GET", "/sse", headers={**self.headers, "Accept": "text/event-stream"})
                self.response = self.connection.getresponse()
                require(self.response.status == 200, "SSE did not return HTTP 200")
                require("text/event-stream" in self.response.getheader("Content-Type", ""), "Not SSE")
                if self.connection.sock:
                    self.connection.sock.settimeout(timeout)
                break
            except (OSError, http.client.HTTPException):
                self.connection.close()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Gateway never opened SSE")
                time.sleep(0.1)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            event, endpoint = self.messages.get(timeout=timeout)
            require(event == "endpoint", "SSE did not announce its message endpoint")
            self.path = message_path(endpoint, port)
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for event, data in sse_events(self.response):
                self.messages.put((event, data))
        except Exception as error:
            self.messages.put(("failure", str(error)))
        finally:
            self.messages.put(("closed", "SSE stream ended"))

    def send(self, payload):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        try:
            connection.request("POST", self.path, json.dumps(payload), {**self.headers, "Content-Type": "application/json"})
            response = connection.getresponse()
            require(response.status in {200, 202}, "MCP POST was not accepted")
            require(len(response.read(1_048_577)) <= 1_048_576, "Oversized POST acknowledgement")
        finally:
            connection.close()

    def rpc(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MCP response deadline exceeded: " + method)
            event, data = self.messages.get(timeout=remaining)
            require(event not in {"failure", "closed"}, data)
            if event != "message":
                continue
            payload = json.loads(data)
            if payload.get("id") != request_id:
                continue  # Only these simple tools are used; no sampling/elicitation capability is granted.
            require("error" not in payload, "MCP protocol error: " + json.dumps(payload.get("error")))
            require("result" in payload, "Missing MCP result")
            return payload["result"]

    def initialize(self, version):
        result = self.rpc("initialize", {"protocolVersion": version, "capabilities": {},
                                          "clientInfo": {"name": "mealprep-smoke", "version": "1.0.0"}})
        require(result.get("protocolVersion") == version, "Unsupported negotiated protocol")
        require("tools" in result.get("capabilities", {}), "No tool capability")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def tools(self):
        tools, cursor = [], None
        for _ in range(10):
            result = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
        raise AssertionError("Too many tools/list pages")

    def close(self):
        if self.connection.sock:
            try:
                self.connection.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.connection.close()
        self.reader.join(timeout=2)


def docker(*args, timeout=60):
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Docker command failed: " + result.stderr.strip())
    return (result.stdout + (result.stderr if args[0] == "logs" else "")).strip()


def tool(client, name, arguments):
    result = client.rpc("tools/call", {"name": name, "arguments": arguments})
    require(not result.get("isError"), "Tool returned isError: " + json.dumps(result))
    return result


def text(result):
    return "\n".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")


class Smoke:
    secret_values = (SYNTHETIC_KEY,)

    def __init__(self, image, output):
        self.image, self.output, self.run_id = image, output, uuid.uuid4().hex[:12]
        self.prefix = "mealprep-smoke-" + self.run_id
        self.network, self.containers, self.volume = None, [], None
        self.key_file = output / "synthetic-key"
        self.key_file.write_text(SYNTHETIC_KEY + "\n")
        self.key_file.chmod(0o444)
        self.catalog = json.loads((ROOT / "tests/integration-catalog.json").read_text())
        self.report = {"status": "incomplete", "imageID": docker("image", "inspect", "--format", "{{.Id}}", image),
                       "startupSHA256": hashlib.sha256((ROOT / "startup.sh").read_bytes()).hexdigest(),
                       "catalog": self.catalog, "cases": [], "cleanup": [],
                       "limits": "Legacy SSE/2025 protocol and synthetic keys/data only; no real credentials, TLS or external-provider validation."}

    def write(self):
        (self.output / "summary.json").write_text(json.dumps(self.report, indent=2) + "\n")

    def container(self, role, env=None, fixture=False, key_file=None):
        args = ["create", "--pull=never", "--name", self.prefix + "-" + role, "--label", LABEL + "=" + self.run_id,
                "--network", self.network, "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256",
                "--memory=1g", "--cpus=1"]
        if fixture:
            args += ["--network-alias", "fixture", "--entrypoint", "python3"]
        else:
            args += ["--publish", "127.0.0.1::8081"]
            args += ["--env", "MCP_API_KEY_FILE=/tmp/mealprep-gateway-key"]
            if role == "memory":
                args += ["--mount", "type=volume,source=" + self.volume + ",target=/data/memory"]
        for key, value in (env or {}).items():
            args += ["--env", key + "=" + value]
        args.append(self.image)
        if fixture:
            args += ["-c", FIXTURE]
        container = docker(*args)
        self.containers.append((container, role))
        if not fixture:
            docker("cp", str(key_file or self.key_file), container + ":/tmp/mealprep-gateway-key")
        docker("start", container)
        return container

    def stop(self, container, role, expected_codes=(0, 143)):
        require(docker("inspect", "--format", '{{index .Config.Labels "' + LABEL + '"}}', container) == self.run_id,
                "Cleanup ownership mismatch")
        docker("stop", "--time", "15", container, timeout=30)
        state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        logs = docker("logs", container)
        secret_leaked = any(value in logs for value in self.secret_values)
        for value in self.secret_values:
            logs = logs.replace(value, "<synthetic-key-redacted>")
        (self.output / (role + ".log")).write_text(logs + "\n")
        docker("rm", container)
        self.containers.remove((container, role))
        result = {"role": role, "exitCode": state["ExitCode"], "oomKilled": state["OOMKilled"],
                  "secretLeaked": secret_leaked,
                  "graceful": state["ExitCode"] in expected_codes and not state["OOMKilled"] and not secret_leaked}
        self.report["cleanup"].append(result)
        return result

    def connect(self, container):
        require(docker("exec", container, "id", "-u") == "1000", "Gateway is not non-root")
        require(SYNTHETIC_KEY not in docker("exec", container, "cat", "/proc/1/cmdline"), "Key value entered gateway argv")
        require(SYNTHETIC_KEY not in docker("inspect", "--format", "{{json .Config.Env}}", container), "Key value entered Docker configured environment")
        ports = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", container))
        binding = ports["8081/tcp"][0]
        require(binding["HostIp"] == "127.0.0.1", "Test port is not loopback-only")
        client = SseClient(int(binding["HostPort"]))
        try:
            for method, path in [("GET", "/sse"), ("POST", client.path)]:
                for key in [None, "synthetic-wrong-key"]:
                    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=5)
                    try:
                        headers = {"Content-Type": "application/json"}
                        if key:
                            headers["Authorization"] = "Bearer " + key
                        connection.request(method, path, "{}" if method == "POST" else None, headers)
                        response = connection.getresponse()
                        require(response.status == 401, "Missing/wrong key was not refused: " + method)
                        response.read()
                    finally:
                        connection.close()
            return client
        except Exception:
            client.close()
            raise

    def case(self, server, allow_private=False):
        name = server["name"] + ("-fixture" if allow_private else "")
        result = {"name": name, "status": "incomplete", "requestedPackage": server["package"]}
        self.report["cases"].append(result)
        env = {"MCP_SERVER_TYPE": server["name"], "MCP_COMMAND_TYPE": server["runner"], "MCP_PACKAGE": server["package"],
               "MCP_PORT": "8081", "MCP_TRANSPORT": "sse", "MEMORY_FILE_PATH": "/data/memory/memory.jsonl"}
        if allow_private:
            env["MCP_ARGS"] = "--allow-private-ips"  # Test-only fixture route, never a production default.
        container, client = None, None
        try:
            container = self.container(name, env)
            copied = docker("exec", container, "sha256sum", "/app/startup.sh").split()[0]
            require(copied == self.report["startupSHA256"], "Image launcher differs from checkout")
            runtime = json.loads(docker("exec", container, "node", "-e", "console.log(JSON.stringify({node:process.version,gateway:require('/usr/local/lib/node_modules/supergateway/package.json').version}))"))
            require(runtime["gateway"] == self.catalog["gatewayVersion"], "Gateway version differs from catalog")
            result["runtime"] = runtime
            client = self.connect(container)
            result["authentication"] = "absent/wrong keys refused on SSE and POST; correct key completes MCP calls"
            result["uid"] = 1000
            initialization = client.initialize(self.catalog["protocolVersion"])
            result["serverInfo"] = initialization.get("serverInfo")
            result["protocolVersion"] = initialization["protocolVersion"]
            names = {entry["name"] for entry in client.tools()}
            require(set(server["tools"]) <= names, "Expected integration tools are missing")
            result["toolCount"] = len(names)
            if server["name"] == "everything":
                require(MARKER in text(tool(client, "echo", {"message": MARKER})), "Echo did not return marker")
                result["verified"] = ["initialize", "tools/list", "echo"]
            elif server["name"] == "memory":
                entity = "synthetic-" + self.run_id
                tool(client, "create_entities", {"entities": [{"name": entity, "entityType": "test", "observations": [MARKER]}]})
                require(MARKER in text(tool(client, "open_nodes", {"names": [entity]})), "Memory read did not return observation")
                # Remove the original container, not just restart its process.
                stopped = self.stop(container, name)
                container = None
                require(stopped["graceful"], "First Memory shutdown failed")
                client.close()
                client = None
                (self.output / "memory.log").rename(self.output / "memory-before-recreation.log")
                container = self.container(name, env)
                client = self.connect(container)
                client.initialize(self.catalog["protocolVersion"])
                require(MARKER in text(tool(client, "open_nodes", {"names": [entity]})), "Memory did not survive container recreation")
                tool(client, "delete_entities", {"entityNames": [entity]})
                require(MARKER not in text(tool(client, "open_nodes", {"names": [entity]})), "Memory deletion not reflected")
                result["verified"] = ["initialize", "tools/list", "create_entities", "open_nodes", "delete_entities"]
                result["verified"].append("named-volume persistence across container removal/recreation")
            else:
                arguments = {"url": "http://fixture:8080/", "raw": True, "max_length": 1024}
                if allow_private:
                    require(MARKER in text(tool(client, "fetch", arguments)), "Fetch did not return fixture marker")
                    result["verified"] = ["initialize", "tools/list", "fetch synthetic fixture with test-only private-IP opt-in"]
                else:
                    refused = client.rpc("tools/call", {"name": "fetch", "arguments": arguments})
                    require(refused.get("isError") and any(word in text(refused).lower() for word in ["private", "non-public", "not globally routable"]), "Default Fetch did not refuse private fixture")
                    result["verified"] = ["initialize", "tools/list", "default private-IP refusal"]
            result["status"] = "passed"
        except Exception as error:
            result.update(status="failed", error=str(error))
        finally:
            try:
                if container:
                    # Stop while the MCP connection is still open, not only after
                    # SSE teardown has already ended the backend session.
                    stopped = self.stop(container, name)
                    if not stopped["graceful"]:
                        result.update(status="failed", shutdown="Non-graceful container exit")
            finally:
                if client:
                    client.close()
            self.write()

    def run(self):
        try:
            self.network = docker("network", "create", "--label", LABEL + "=" + self.run_id, self.prefix)
            self.volume = docker("volume", "create", "--label", LABEL + "=" + self.run_id, self.prefix + "-memory")
            self.startup_rejections()
            self.container("fixture", fixture=True)
            for server in self.catalog["servers"]:
                self.case(server)
                if server["name"] == "fetch":
                    self.case(server, allow_private=True)
            self.report["status"] = "passed" if all(case["status"] == "passed" for case in self.report["cases"]) else "failed"
        finally:
            for container, role in list(self.containers):
                self.stop(container, role)
            if self.network:
                require(docker("network", "inspect", "--format", '{{index .Labels "' + LABEL + '"}}', self.network) == self.run_id,
                        "Network cleanup ownership mismatch")
                docker("network", "rm", self.network)
                self.report["networkRemoved"] = True
            if getattr(self, "volume", None):
                require(docker("volume", "inspect", "--format", '{{index .Labels "' + LABEL + '"}}', self.volume) == self.run_id,
                        "Volume cleanup ownership mismatch")
                docker("volume", "rm", self.volume)
                self.report["volumeRemoved"] = True
            if self.report["status"] == "passed" and any(not entry["graceful"] for entry in self.report["cleanup"]):
                self.report["status"] = "failed"
            self.write()
        return self.report

    def startup_rejections(self):
        empty = self.output / "empty-synthetic-key"
        empty.write_text("")
        empty.chmod(0o444)
        self.report["startupRejections"] = []
        for role, path, source in [
            ("missing-key", "/tmp/missing-key-file", self.key_file),
            ("empty-key", "/tmp/mealprep-gateway-key", empty),
        ]:
            container = self.container(role, {"MCP_COMMAND_TYPE": "npx", "MCP_PACKAGE": "must-not-launch",
                                              "MCP_API_KEY_FILE": path}, key_file=source)
            require(docker("wait", container, timeout=15) == "1", "Invalid key did not fail startup")
            stopped = self.stop(container, role, expected_codes=(1,))
            require(stopped["graceful"], "Invalid-key startup case failed")
            self.report["startupRejections"].append({"name": role, "exitCode": 1, "status": "passed"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Reviewed local image; never pulled or published by this script")
    parser.add_argument("--output", required=True, type=Path, help="New private evidence directory; refuses reuse")
    options = parser.parse_args()
    options.output.mkdir(mode=0o700)
    result = Smoke(options.image, options.output).run()
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
