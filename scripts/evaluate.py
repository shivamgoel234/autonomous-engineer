"""Measure scripted fixture runs. This is an integration benchmark, not AI performance."""

import argparse
import json
import tempfile
import threading
from pathlib import Path

from ase.config import Settings
from ase.demos import DEMOS
from ase.engine import Engine
from ase.runner import DockerRunner, TrustedDemoRunner
from ase.service import Service
from ase.store import Store

parser = argparse.ArgumentParser()
parser.add_argument("--docker", action="store_true", help="Use the prebuilt ase-sandbox:1 image")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
results = []
with tempfile.TemporaryDirectory(prefix="ase-evaluation-") as directory:
    settings = Settings(
        data_dir=Path(directory),
        owner_token="evaluation-token-not-for-deployment",
        runner="docker" if args.docker else "trusted-demo",
    )
    store = Store(settings.data_dir / "ase.sqlite3")
    runner = DockerRunner(settings.sandbox_image) if args.docker else TrustedDemoRunner()
    service = Service(settings, store, runner)
    engine = Engine(settings, store, runner, threading.Event())
    for scenario, spec in DEMOS.items():
        project = service.demo(scenario)
        run, _ = store.create_run(project["id"], spec["task"], scenario, scenario)
        engine.execute(run["id"])
        item = store.run(run["id"])
        results.append(
            dict(
                scenario=scenario,
                status=item["status"],
                attempts=item["attempt"],
                seconds=item["elapsed_seconds"],
                tests=item["tests"][-1] if item["tests"] else None,
            )
        )
report = dict(
    benchmark="scripted-fixture-integration",
    runner=settings.runner,
    resolved=sum(r["status"] == "awaiting_review" for r in results),
    total=len(results),
    results=results,
)
serialized = json.dumps(report, indent=2)
print(serialized)
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
if report["resolved"] != report["total"]:
    raise SystemExit(1)
