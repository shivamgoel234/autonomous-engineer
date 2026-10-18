import hashlib
import json
import queue
import shutil
import tempfile
import threading
from pathlib import Path

from .demos import DEMOS, write_demo
from .domain import PolicyError
from .engine import Engine
from .runner import DockerRunner, TrustedDemoRunner
from .workspace import import_zip


class Overloaded(Exception):
    pass


class Service:
    def __init__(self, settings, store, runner=None, provider_factory=None):
        self.settings, self.store = settings, store
        self.queue = queue.Queue(maxsize=settings.queue_size)
        self.stopping = threading.Event()
        self.submit_lock = threading.Lock()
        runner = runner or (
            DockerRunner(settings.sandbox_image)
            if settings.runner == "docker"
            else TrustedDemoRunner()
        )
        self.engine = Engine(settings, store, runner, self.stopping, provider_factory)
        self.worker = threading.Thread(target=self.work, name="agent-worker", daemon=True)

    def start(self):
        self.store.recover()
        self.worker.start()

    def close(self):
        self.stopping.set()
        self.worker.join(timeout=35)

    def work(self):
        while not self.stopping.is_set():
            try:
                run_id = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.engine.execute(run_id)
            finally:
                self.queue.task_done()

    def demo(self, scenario):
        if scenario not in DEMOS:
            raise KeyError(scenario)
        spec = DEMOS[scenario]
        project = self.store.add_project(spec["name"], f"demo:{scenario}")
        write_demo(self.settings.data_dir / "projects" / project["id"], scenario)
        return {**project, "suggested_task": spec["task"]}

    def upload(self, name, payload):
        if self.settings.runner != "docker" or self.settings.provider != "openai":
            raise PolicyError("Custom repository upload requires Docker and the OpenAI provider.")
        with tempfile.TemporaryDirectory(dir=self.settings.data_dir) as temp:
            root = Path(temp) / "repository"
            import_zip(payload, root)
            project = self.store.add_project(name, "upload")
            destination = self.settings.data_dir / "projects" / project["id"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(root, destination)
        return project

    def submit(self, project_id, task, key):
        project = self.store.project(project_id)
        if self.settings.provider == "demo":
            scenario = project["kind"].split(":")[-1]
            if scenario not in DEMOS or task != DEMOS[scenario]["task"]:
                raise PolicyError("Scripted demo runs only support the displayed fixture task.")
        fingerprint = hashlib.sha256(json.dumps([project_id, task]).encode()).hexdigest()
        with self.submit_lock:
            with self.store.connect() as db:
                existing = db.execute("SELECT id FROM runs WHERE request_key=?", (key,)).fetchone()
            if self.queue.full() and existing is None:
                raise Overloaded("Queue full; retry later with the same key.")
            run, created = self.store.create_run(project_id, task, key, fingerprint)
            if created:
                self.store.event(run["id"], "queued", "Run queued")
                self.queue.put_nowait(run["id"])
        return run, created
