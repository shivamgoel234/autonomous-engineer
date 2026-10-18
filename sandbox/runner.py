"""Fixed test harness. Runs inside the sandbox; source is mounted read-only."""

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

report = Path("/tmp/ase-report.xml")
process = subprocess.run(
    [
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--disable-warnings",
        f"--junitxml={report}",
        "tests",
    ],
    cwd="/workspace",
    capture_output=True,
    text=True,
)
result = dict(
    exit_code=process.returncode,
    passed=0,
    failed=0,
    errors=0,
    skipped=0,
    output=(process.stdout + process.stderr)[-24000:],
)
if report.exists() and report.stat().st_size < 1_000_000:
    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.attrib.get("tests", 0)) for s in suites)
    for field, xml_field in [("failed", "failures"), ("errors", "errors"), ("skipped", "skipped")]:
        result[field] = sum(int(s.attrib.get(xml_field, 0)) for s in suites)
    result["passed"] = total - result["failed"] - result["errors"] - result["skipped"]
print(json.dumps(result))
