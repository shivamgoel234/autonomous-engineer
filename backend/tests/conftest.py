import time

import pytest
from ase.api import create_app
from ase.config import Settings
from ase.domain import TERMINAL
from fastapi.testclient import TestClient

OWNER = "owner-test-token-with-at-least-24-chars"
REVIEWER = "reviewer-test-token-with-at-least-24-chars"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path, runner="trusted-demo", owner_token=OWNER, reviewer_token=REVIEWER
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as connection:
        connection.headers.update({"Authorization": f"Bearer {OWNER}"})
        yield connection


def wait_for_run(client, run_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in TERMINAL:
            return run
        time.sleep(0.05)
    raise AssertionError("Run did not terminate within test deadline")


def start_demo(client, scenario="cart", key="unique-test-key"):
    project = client.post(f"/api/v1/projects/demo/{scenario}").json()
    response = client.post(
        "/api/v1/runs",
        headers={"Idempotency-Key": key},
        json={"project_id": project["id"], "task": project["suggested_task"]},
    )
    assert response.status_code == 202
    return project, response.json()
