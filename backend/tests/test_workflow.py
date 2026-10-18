from dataclasses import replace

import pytest
from ase.api import create_app
from ase.demos import DEMOS
from ase.domain import Action
from ase.domain import TestResult as ExecutionResult
from ase.store import Store
from conftest import REVIEWER, start_demo, wait_for_run
from fastapi.testclient import TestClient


@pytest.mark.parametrize("scenario", list(DEMOS))
def test_real_demo_repairs_then_requires_human_review(client, settings, scenario):
    project, submitted = start_demo(client, scenario)
    run = wait_for_run(client, submitted["id"])
    assert run["status"] == "awaiting_review"
    assert run["attempt"] == 2
    assert run["tests"][0]["failed"] > 0
    assert run["tests"][1]["failed"] > 0
    assert run["tests"][-1]["failed"] == 0
    assert run["tests"][-1]["passed"] > 0
    original = settings.data_dir / "projects" / project["id"] / "src/solution.py"
    assert original.read_text() == DEMOS[scenario]["source"]
    assert run["changed_files"] == ["src/solution.py"]
    assert client.get(f"/api/v1/runs/{run['id']}/patch").status_code == 409
    reviewed = client.post(
        f"/api/v1/runs/{run['id']}/review",
        headers={"Authorization": f"Bearer {REVIEWER}"},
        json={"decision": "approved"},
    )
    assert reviewed.json()["status"] == "approved"
    assert client.get(f"/api/v1/runs/{run['id']}/patch").text.startswith("--- a/src/")
    assert (
        client.post(f"/api/v1/runs/{run['id']}/review", json={"decision": "rejected"}).status_code
        == 409
    )
    assert any(e["kind"] == "review" for e in client.app.state.store.events(run["id"]))


def test_idempotent_retry_and_conflicting_reuse(client):
    project, run = start_demo(client)
    body = {"project_id": project["id"], "task": project["suggested_task"]}
    duplicate = client.post(
        "/api/v1/runs", headers={"Idempotency-Key": "unique-test-key"}, json=body
    )
    assert duplicate.json()["id"] == run["id"]
    another = client.post("/api/v1/projects/demo/cart").json()
    body["project_id"] = another["id"]
    assert (
        client.post(
            "/api/v1/runs", headers={"Idempotency-Key": "unique-test-key"}, json=body
        ).status_code
        == 409
    )


def test_authentication_and_role_boundaries(client):
    assert (
        client.get("/api/v1/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    header = {"Authorization": f"Bearer {REVIEWER}"}
    assert client.get("/api/v1/projects", headers=header).status_code == 200
    assert client.post("/api/v1/projects/demo/cart", headers=header).status_code == 403
    assert client.get("/api/v1/runs/not-a-run").status_code == 404


def test_sse_replay_and_persistent_history(client):
    _, submitted = start_demo(client)
    run = wait_for_run(client, submitted["id"])
    events = client.app.state.store.events(run["id"])
    response = client.get(f"/api/v1/runs/{run['id']}/events?after={events[-2]['id']}")
    assert response.status_code == 200
    assert "event: done" in response.text
    assert f"id: {events[-1]['id']}" in response.text
    assert f"id: {events[0]['id']}\n" not in response.text
    assert len(client.get("/api/v1/runs").json()) == 1


def test_demo_rejects_arbitrary_task_and_upload(client):
    project = client.post("/api/v1/projects/demo/cart").json()
    assert (
        client.post(
            "/api/v1/runs",
            headers={"Idempotency-Key": "unknown-task-key"},
            json={"project_id": project["id"], "task": "Do a different thing please"},
        ).status_code
        == 422
    )
    assert client.post("/api/v1/projects/upload", content=b"anything").status_code == 422
    assert client.post("/api/v1/projects/upload", content=b"x" * 2_000_001).status_code == 413


class FailingRunner:
    def run(self, workspace, stop, timeout):
        stop()
        return ExecutionResult(1, failed=1, output="acceptance failed")


class FinishProvider:
    def next_action(self, history, remaining):
        if history[-1]["kind"] == "attempt":
            return Action("record_plan", {"steps": ["Verify existing code"]})
        return Action("finish", {"summary": "I fixed everything, all tests pass!"})


def test_model_claim_does_not_override_test_evidence(settings):
    with TestClient(
        create_app(settings, FailingRunner(), lambda project: FinishProvider())
    ) as client:
        from conftest import OWNER

        client.headers.update({"Authorization": f"Bearer {OWNER}"})
        _, submitted = start_demo(client)
        run = wait_for_run(client, submitted["id"])
        assert run["status"] == "failed_tests"
        assert run["attempt"] == 3
        assert all(t["exit_code"] == 1 for t in run["tests"])
        assert (
            client.post(
                f"/api/v1/runs/{run['id']}/review", json={"decision": "approved"}
            ).status_code
            == 409
        )


def test_zero_collected_tests_are_not_success(settings):
    class EmptyRunner:
        def run(self, workspace, stop, timeout):
            return ExecutionResult(0)

    with TestClient(create_app(settings, EmptyRunner())) as client:
        from conftest import OWNER

        client.headers.update({"Authorization": f"Bearer {OWNER}"})
        _, submitted = start_demo(client)
        assert wait_for_run(client, submitted["id"])["status"] == "failed_tests"


def test_cancellation_is_observed_during_test_process(client):
    _, submitted = start_demo(client)
    response = client.post(f"/api/v1/runs/{submitted['id']}/cancel")
    assert response.status_code == 202
    assert wait_for_run(client, submitted["id"])["status"] == "cancelled"


def test_budget_exhaustion_stops_unbounded_model_loop(settings):
    limited = replace(settings, max_tool_calls=1)
    with TestClient(
        create_app(limited, FailingRunner(), lambda project: FinishProvider())
    ) as client:
        from conftest import OWNER

        client.headers.update({"Authorization": f"Bearer {OWNER}"})
        _, submitted = start_demo(client)
        assert wait_for_run(client, submitted["id"])["status"] == "budget_exhausted"


def test_abandoned_runs_become_interrupted(client, settings):
    project = client.post("/api/v1/projects/demo/cart").json()
    store = Store(settings.data_dir / "ase.sqlite3")
    run, _ = store.create_run(project["id"], "pending task", "recovery-key", "fingerprint")
    store.recover()
    assert store.run(run["id"])["status"] == "interrupted"


def test_generated_code_requires_docker(settings):
    with pytest.raises(ValueError, match="requires Docker"):
        replace(settings, provider="openai", api_key="test", model="configured-model").validate()
