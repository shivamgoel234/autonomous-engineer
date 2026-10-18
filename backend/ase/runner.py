"""One fixed test command. No model-controlled shell or environment."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .domain import RunStopped, TestResult


def execute(command, cwd, stop, timeout, env):
    tail = bytearray()
    lock = threading.Lock()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=os.name != "nt",
    )

    def drain():
        while chunk := process.stdout.read(4096):
            with lock:
                tail.extend(chunk)
                del tail[:-32000]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            stop()
            if time.monotonic() >= deadline:
                raise RunStopped("timeout")
            time.sleep(0.05)
        stop()
    finally:
        if process.poll() is None:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        reader.join(timeout=2)
        process.stdout.close()
    with lock:
        return process.returncode, tail.decode("utf-8", errors="replace")


class DockerRunner:
    def __init__(self, image):
        self.image = image

    def run(self, workspace: Path, stop, timeout):
        name = "ase-" + uuid.uuid4().hex
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cpus=1",
            "--memory=512m",
            "--memory-swap=512m",
            "--pids-limit=64",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=64m",
            "--mount",
            f"type=bind,source={workspace.resolve()},target=/workspace,readonly",
            self.image,
        ]
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "DOCKER_HOST", "XDG_RUNTIME_DIR")
            if key in os.environ
        }
        try:
            code, output = execute(command, workspace, stop, timeout, env)
            if code != 0:
                raise RuntimeError("Sandbox failed. Build the image and verify Docker is running.")
            result = json.loads(output.strip().splitlines()[-1])
            return TestResult(**result)
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10, env=env)


class TrustedDemoRunner:
    """Only constructed for bundled scripted fixtures. Not a security sandbox."""

    def run(self, workspace: Path, stop, timeout):
        with tempfile.TemporaryDirectory(prefix="ase-report-") as directory:
            report = Path(directory) / "report.xml"
            env = {
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
                if key in os.environ
            }
            env.update(
                PYTHONDONTWRITEBYTECODE="1",
                PYTHONUNBUFFERED="1",
                PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            )
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--disable-warnings",
                f"--junitxml={report}",
                "tests",
            ]
            code, output = execute(command, workspace, stop, timeout, env)
            result = TestResult(code, output=output)
            if report.exists():
                root = ET.parse(report).getroot()
                suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
                total = sum(int(s.attrib.get("tests", 0)) for s in suites)
                for field, attr in [
                    ("failed", "failures"),
                    ("errors", "errors"),
                    ("skipped", "skipped"),
                ]:
                    setattr(result, field, sum(int(s.attrib.get(attr, 0)) for s in suites))
                result.passed = total - result.failed - result.errors - result.skipped
            return result
