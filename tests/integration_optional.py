"""Explicit Streamable HTTP + separate mcpo image smoke; synthetic keys only."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import time

from integration_smoke import LABEL, MARKER, ROOT, SYNTHETIC_KEY, Smoke, docker, require, sse_events, text, tool

BRIDGE_KEY = "synthetic-distinct-mcpo-inbound-key-not-for-deployment"
WRONG_UPSTREAM_KEY = "synthetic-wrong-upstream-key-not-the-inbound-key"
DEFAULT_KEY = object()


class HttpClient:
    def __init__(self, port, key=SYNTHETIC_KEY):
        self.port, self.session, self.sequence = port, None, 0
        self.key = key

    def request(self, method, payload=None, key=DEFAULT_KEY):
        if key is DEFAULT_KEY:
            key = self.key
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                   "MCP-Protocol-Version": "2025-11-25"}
        if key:
            headers["Authorization"] = "Bearer " + key
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        try:
            connection.request(method, "/mcp", json.dumps(payload) if payload is not None else None, headers)
            response = connection.getresponse()
            self.session = response.getheader("Mcp-Session-Id") or self.session
            content_type = response.getheader("Content-Type", "")
            if response.status == 200 and "text/event-stream" in content_type:
                for event, data in sse_events(response):
                    if event == "message":
                        result = json.loads(data)
                        if result.get("id") == (payload or {}).get("id"):
                            return response.status, result
                raise AssertionError("No matching Streamable HTTP response")
            body = response.read(1_048_577)
            require(len(body) <= 1_048_576, "Oversized HTTP response")
            return response.status, json.loads(body) if body else None
        finally:
            connection.close()

    def send(self, payload):
        status, _ = self.request("POST", payload)
        require(status == 202, "Notification not accepted")

    def rpc(self, method, params=None):
        self.sequence += 1
        payload = {"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params or {}}
        status, result = self.request("POST", payload)
        require(status == 200 and isinstance(result, dict), "MCP response missing")
        require(result.get("id") == self.sequence and "result" in result and "error" not in result,
                "MCP result did not complete successfully")
        return result["result"]

    def initialize(self):
        result = self.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                          "clientInfo": {"name": "mealprep-http-smoke", "version": "1"}})
        require(result.get("protocolVersion") == "2025-11-25", "Unexpected negotiated protocol")
        require(self.session, "Stateful HTTP did not issue a session ID")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def close(self):
        if self.session:
            status, _ = self.request("DELETE")
            require(status == 200, "Session DELETE failed")
            status, _ = self.request("POST", {"jsonrpc": "2.0", "id": 999, "method": "ping"})
            require(status == 404, "Deleted session remained usable")
            self.session = None


def openapi_request(port, method, path, key=BRIDGE_KEY, payload=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
        response = connection.getresponse()
        body = response.read(1_048_577)
        require(len(body) <= 1_048_576, "Oversized OpenAPI response")
        return response.status, body
    finally:
        connection.close()


class OptionalSmoke(Smoke):
    secret_values = (SYNTHETIC_KEY, BRIDGE_KEY, WRONG_UPSTREAM_KEY)

    def __init__(self, image, bridge_image, output):
        super().__init__(image, output)
        self.bridge_image = bridge_image
        self.bridge_file = output / "synthetic-bridge-key"
        self.bridge_file.write_text(BRIDGE_KEY + "\n")
        self.bridge_file.chmod(0o444)
        self.report.update(bridgeImageID=docker("image", "inspect", "--format", "{{.Id}}", bridge_image),
                           bridgeSHA256=hashlib.sha256((ROOT / "mcpo_bridge.py").read_bytes()).hexdigest(),
                           limits="Synthetic protocol smoke only; no client apps, models, real credentials or TLS.")

    def port(self, container, port):
        binding = json.loads(docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", container))[str(port) + "/tcp"][0]
        require(binding["HostIp"] == "127.0.0.1", "Port is not loopback-only")
        require(docker("exec", container, "id", "-u") == "1000", "Container is root")
        for value in self.secret_values:
            require(value not in docker("exec", container, "cat", "/proc/1/cmdline"), "Key entered argv")
            require(value not in docker("inspect", "--format", "{{json .Config.Env}}", container), "Key entered configured env")
        return int(binding["HostPort"])

    def bridge(self, role="bridge", upstream_file=None):
        container = docker("create", "--pull=never", "--name", self.prefix + "-" + role,
                           "--label", LABEL + "=" + self.run_id, "--network", self.network,
                           "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256",
                           "--memory=1g", "--cpus=1", "--publish", "127.0.0.1::8000",
                           "--env", "MCPO_API_KEY_FILE=/tmp/bridge-key",
                           "--env", "MCP_API_KEY_FILE=/tmp/gateway-key",
                           "--env", "MCPO_UPSTREAM_URL=http://" + self.prefix + "-everything:8081/mcp",
                           self.bridge_image)
        self.containers.append((container, role))
        docker("cp", str(self.bridge_file), container + ":/tmp/bridge-key")
        docker("cp", str(upstream_file or self.key_file), container + ":/tmp/gateway-key")
        docker("start", container)
        if role == "bridge":
            require(docker("exec", container, "sha256sum", "/app/mcpo_bridge.py").split()[0] == self.report["bridgeSHA256"],
                    "Bridge source/image mismatch")
        return container

    def bridge_case(self, native):
        result = {"name": "mcpo", "status": "incomplete"}
        self.report["cases"].append(result)
        container = None
        try:
            config = json.loads(docker("compose", "--env-file", "/dev/null", "-f", str(ROOT / "docker-compose.yml"),
                                       "-f", str(ROOT / "docker-compose.mcpo.yml"), "config", "--format", "json"))
            probe = config["services"]["mcp-mealprep-everything"]["healthcheck"]["test"]
            require(probe[0] == "CMD", "Unexpected readiness command")
            docker("exec", self.prefix + "-everything", *probe[1:])
            container = self.bridge()
            port = self.port(container, 8000)
            deadline = time.monotonic() + 120
            while True:
                try:
                    status, body = openapi_request(port, "GET", "/openapi.json")
                    require(status == 200, "Authenticated schema unavailable")
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Bridge never served its schema")
                    require(docker("inspect", "--format", "{{.State.Running}}", container) == "true", "Bridge exited before readiness")
                    time.sleep(0.1)
            schema = json.loads(body)
            require("post" in schema.get("paths", {}).get("/echo", {}), "Echo missing from schema")
            for origin, allowed in [("http://localhost:3000", True), ("https://untrusted.example", False)]:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    connection.request("OPTIONS", "/echo", headers={"Origin": origin,
                                       "Access-Control-Request-Method": "POST",
                                       "Access-Control-Request-Headers": "authorization,content-type"})
                    response = connection.getresponse()
                    require(response.status == (200 if allowed else 400), "Unexpected CORS preflight status")
                    require(response.getheader("Access-Control-Allow-Origin") == (origin if allowed else None),
                            "CORS origin policy was not enforced")
                    response.read()
                finally:
                    connection.close()
            for method, path in [("GET", "/openapi.json"), ("GET", "/docs"), ("POST", "/echo")]:
                for key in [None, "synthetic-wrong-key", SYNTHETIC_KEY]:
                    status, _ = openapi_request(port, method, path, key, {"message": MARKER} if method == "POST" else None)
                    require(status in {401, 403}, "Unauthorized OpenAPI request accepted")
            status, body = openapi_request(port, "POST", "/echo", payload={"message": MARKER})
            require(status == 200 and MARKER in body.decode(), "OpenAPI echo did not return synthetic marker")
            require(MARKER in text(tool(native, "echo", {"message": MARKER})), "Native MCP failed while bridge was connected")
            versions = json.loads(docker("exec", container, "/opt/mcpo/bin/python", "-c",
                                        "import json,importlib.metadata as m;print(json.dumps({n:m.version(n) for n in ['mcpo','mcp','fastapi','starlette']}))"))
            expected_versions = self.catalog.get("bridgeVersions")
            require(isinstance(expected_versions, dict) and expected_versions, "Bridge version catalog entry missing")
            require(versions == expected_versions, "Bridge dependency versions differ from catalog: " + json.dumps(versions))
            result.update(status="passed", versions=versions,
                          verified=["authenticated OpenAPI schema and echo", "schema/docs/tools reject absent, wrong and gateway keys",
                                    "native MCP call with bridge concurrently connected", "UID 1000 and keys absent from argv/configured env",
                                    "overlay readiness command against actual gateway", "allowed and foreign CORS preflights"])
        except Exception as error:
            result.update(status="failed", error=str(error))
        finally:
            if container:
                require(self.stop(container, "bridge")["graceful"], "Bridge shutdown failed")
            self.write()

    def upstream_rejection(self):
        wrong = self.output / "synthetic-wrong-upstream-key"
        wrong.write_text(WRONG_UPSTREAM_KEY + "\n")
        wrong.chmod(0o444)
        container = self.bridge("wrong-upstream", upstream_file=wrong)
        exit_code = docker("wait", container, timeout=30)
        require(exit_code not in {"0", "137"}, "Bad upstream auth did not cause a startup failure")
        stopped = self.stop(container, "wrong-upstream", expected_codes=(int(exit_code),))
        require(stopped["graceful"], "Bad-upstream test leaked secrets or was killed")
        self.report["upstreamAuthFailure"] = {"status": "passed", "exitCode": int(exit_code)}

    def http_case(self, server):
        result = {"name": server["name"] + "-http", "status": "incomplete"}
        self.report["cases"].append(result)
        container, client = None, None
        try:
            env = {"MCP_COMMAND_TYPE": server["runner"], "MCP_PACKAGE": server["package"],
                   "MEMORY_FILE_PATH": "/data/memory/memory.jsonl"}
            if server["name"] == "everything":
                env["MCP_ARGS"] = "stdio"  # Nonempty backend arguments must survive gateway/bridge setup.
            # Do not mount a volume here; original smoke separately proves persistence.
            role = server["name"]
            if role == "memory":
                role = "memory-http"
            container = self.container(role, env)
            require(docker("exec", container, "sha256sum", "/app/startup.sh").split()[0] == self.report["startupSHA256"], "Launcher mismatch")
            port = self.port(container, 8081)
            client = HttpClient(port)
            deadline = time.monotonic() + 120
            while True:
                try:
                    status, _ = client.request("POST", {"jsonrpc": "2.0", "id": 0, "method": "initialize"}, key=None)
                    require(status == 401, "Unauthenticated HTTP accepted")
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("HTTP gateway did not start")
                    time.sleep(0.1)
            for method in ["GET", "POST", "DELETE"]:
                for key in [None, "synthetic-wrong-key", BRIDGE_KEY]:
                    status, _ = client.request(method, key=key)
                    require(status == 401, "Unauthorized HTTP method accepted")
            init = client.initialize()
            tools = client.rpc("tools/list")["tools"]
            require(set(server["tools"]) <= {entry["name"] for entry in tools}, "Tools missing")
            if server["name"] == "everything":
                require(MARKER in text(tool(client, "echo", {"message": MARKER})), "HTTP echo failed")
                self.bridge_case(client)
                self.upstream_rejection()
            elif server["name"] == "memory":
                tool(client, "create_entities", {"entities": [{"name": "synthetic", "entityType": "test", "observations": [MARKER]}]})
                require(MARKER in text(tool(client, "open_nodes", {"names": ["synthetic"]})), "HTTP Memory read failed")
                tool(client, "delete_entities", {"entityNames": ["synthetic"]})
            else:
                refused = client.rpc("tools/call", {"name": "fetch", "arguments": {"url": "http://127.0.0.1/"}})
                require(refused.get("isError") and "private" in text(refused).lower(), "HTTP Fetch did not refuse private IP")
            client.close()
            result.update(status="passed", serverInfo=init.get("serverInfo"), protocolVersion=init["protocolVersion"],
                          verified=["initialize", "tools/list", "representative call", "absent/wrong/bridge keys refused",
                                    "session DELETE and post-deletion refusal", "UID 1000; key not in argv/configured env"])
        except Exception as error:
            result.update(status="failed", error=str(error))
        finally:
            if container:
                role = "memory-http" if server["name"] == "memory" else server["name"]
                require(self.stop(container, role)["graceful"], "HTTP gateway shutdown failed")
            self.write()

    def run(self):
        try:
            self.network = docker("network", "create", "--label", LABEL + "=" + self.run_id, self.prefix)
            for server in self.catalog["servers"]:
                self.http_case(server)
            self.report["status"] = "passed" if len(self.report["cases"]) == 4 and all(c["status"] == "passed" for c in self.report["cases"]) else "failed"
        finally:
            for container, role in list(self.containers):
                self.stop(container, role)
            if self.network:
                require(docker("network", "inspect", "--format", '{{index .Labels "' + LABEL + '"}}', self.network) == self.run_id,
                        "Network ownership mismatch")
                docker("network", "rm", self.network)
                self.report["networkRemoved"] = True
            if any(not c["graceful"] for c in self.report["cleanup"]):
                self.report["status"] = "failed"
            self.write()
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--bridge-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    options.output.mkdir(mode=0o700)
    report = OptionalSmoke(options.image, options.bridge_image, options.output).run()
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
