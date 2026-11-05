"""Local release gate over reviewed images. Never builds, pulls, pushes or signs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def evidence_passes(legacy, optional):
    for report, count in [(legacy, 8), (optional, 5)]:
        if report.get("status") != "passed" or report.get("networkRemoved") is not True:
            return False
        cases = report.get("cases", [])
        cleanup = report.get("cleanup", [])
        if len(cases) != 4 or not all(case.get("status") == "passed" for case in cases):
            return False
        if len(cleanup) != count or not all(
            entry.get("graceful") is True and entry.get("oomKilled") is False
            and entry.get("secretLeaked") is False for entry in cleanup
        ):
            return False
    rejections = legacy.get("startupRejections", [])
    return (legacy.get("volumeRemoved") is True and len(rejections) == 2
            and all(case.get("status") == "passed" and case.get("exitCode") == 1 for case in rejections)
            and optional.get("upstreamAuthFailure") == {"status": "passed", "exitCode": 3})


def source_hashes():
    paths = [ROOT / name for name in ["Dockerfile", ".dockerignore", ".gitignore", "startup.sh",
             "mcpo_bridge.py", "docker-compose.yml", "docker-compose.mcpo.yml", "README.md", "Startup README.md",
             ".github/workflows/docker-publish.yml"]]
    for pattern in ["tests/*.py", "tests/*.json", "examples/*", "docs/*.md", "docs/archive/*"]:
        paths.extend(ROOT.glob(pattern))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths)) if path.is_file()}


def inspect_image(image):
    result = subprocess.run(["docker", "image", "inspect", "--format", "{{json .}}", image],
                            text=True, capture_output=True, check=True)
    info = json.loads(result.stdout)
    if info["Config"].get("User") != "1000:1000":
        raise ValueError("Reviewed images must run as UID/GID 1000:1000.")
    return {"id": info["Id"], "os": info["Os"], "architecture": info["Architecture"],
            "user": info["Config"]["User"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Already-built reviewed local gateway image")
    parser.add_argument("--bridge-image", required=True, help="Already-built reviewed local mcpo target")
    parser.add_argument("--output", type=Path, required=True, help="New private evidence directory; reuse refused")
    options = parser.parse_args()
    if options.output.exists():
        parser.error("Evidence directory already exists; choose a new path.")
    os.umask(0o077)
    options.output.mkdir(mode=0o700)
    output = options.output.resolve()
    report = {"status": "incomplete", "scope": "Local synthetic verification; not release authorization or security certification.",
              "sourceSHA256": source_hashes(), "checks": []}

    def run(name, argv):
        with (output / (name + ".log")).open("w") as log:
            result = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        report["checks"].append({"name": name, "exitCode": result.returncode})
        if result.returncode:
            raise ValueError(name + " failed; inspect its local evidence log.")

    try:
        report["gatewayImage"] = inspect_image(options.image)
        report["bridgeImage"] = inspect_image(options.bridge_image)
        report["baseRevision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        report["workingTree"] = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines()
        run("bash", ["bash", "-n", "startup.sh"])
        for name, extra in [("compose", []), ("compose-mcpo", ["-f", "docker-compose.mcpo.yml"]),
                            ("compose-sse", ["-f", "examples/compose.sse.yml"])]:
            run(name, ["docker", "compose", "--env-file", "/dev/null", "-f", "docker-compose.yml", *extra, "config", "--quiet"])
        # Non-executing parse only: the archived V1 text must not be deployable.
        retired = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f",
                                  "docs/archive/docker-compose-v1.yml.txt", "config", "--quiet"],
                                 cwd=ROOT, text=True, capture_output=True)
        if retired.returncode == 0:
            raise ValueError("Retired archive unexpectedly parsed as deployable Compose.")
        report["checks"].append({"name": "archive-refused", "exitCode": retired.returncode, "expectedFailure": True})
        run("offline", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
        run("legacy", [sys.executable, "tests/integration_smoke.py", "--image", options.image, "--output", str(output / "legacy")])
        run("optional", [sys.executable, "tests/integration_optional.py", "--image", options.image,
                         "--bridge-image", options.bridge_image, "--output", str(output / "optional")])
        legacy = json.loads((output / "legacy/summary.json").read_text())
        optional = json.loads((output / "optional/summary.json").read_text())
        if not evidence_passes(legacy, optional):
            raise ValueError("Live evidence was incomplete or cleanup failed.")
        for evidence in [legacy, optional]:
            if evidence.get("imageID") != report["gatewayImage"]["id"]:
                raise ValueError("Gateway image changed during verification.")
            if evidence.get("startupSHA256") != report["sourceSHA256"]["startup.sh"]:
                raise ValueError("Launcher source/image evidence mismatch.")
        if optional.get("bridgeImageID") != report["bridgeImage"]["id"] or optional.get("bridgeSHA256") != report["sourceSHA256"]["mcpo_bridge.py"]:
            raise ValueError("Bridge source/image evidence mismatch.")
        if source_hashes() != report["sourceSHA256"]:
            raise ValueError("Source changed during verification; rerun on the intended artifact.")
        report["status"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report.update(status="failed", error=str(error))
    finally:
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "evidence": str(output), "error": report.get("error")}, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
