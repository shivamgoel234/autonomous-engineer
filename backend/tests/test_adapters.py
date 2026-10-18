import json
import os
import subprocess

import httpx
import pytest
from ase.domain import RunStopped
from ase.providers import OpenAIProvider
from ase.runner import DockerRunner, execute


def test_openai_tool_roundtrip_preserves_reasoning_and_tool_outputs(monkeypatch):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning", "id": "r1", "summary": []},
                    {
                        "type": "function_call",
                        "name": "read_file",
                        "call_id": "c1",
                        "arguments": '{"path":"src/code.py"}',
                    },
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handle)
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    provider = OpenAIProvider("test-key", "test-model")
    history = [{"kind": "task", "data": {"task": "repair"}}]
    action = provider.next_action(history, 20)
    assert action.name == "read_file"
    history.append({"kind": "tool_result", "data": {"call_id": "c1", "result": "value = 1"}})
    provider.next_action(history, 20)
    assert any(item["type"] == "reasoning" for item in requests[-1]["input"] if "type" in item)
    assert requests[-1]["input"][-1] == {
        "type": "function_call_output",
        "call_id": "c1",
        "output": '"value = 1"',
    }
    assert requests[0]["store"] is False
    assert "api_key" not in requests[0]


def test_docker_command_enforces_boundaries(monkeypatch, tmp_path):
    captured = {}

    def fake_execute(command, cwd, stop, timeout, env):
        captured.update(command=command, env=env)
        return 0, json.dumps(
            dict(exit_code=0, passed=1, failed=0, errors=0, skipped=0, output="ok")
        )

    monkeypatch.setattr("ase.runner.execute", fake_execute)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    result = DockerRunner("test-image").run(tmp_path, lambda: None, 2)
    assert result.ok
    command = captured["command"]
    for flag in [
        "--network=none",
        "--read-only",
        "--cpus=1",
        "--memory=512m",
        "--pids-limit=64",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
    ]:
        assert flag in command
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "docker.sock" not in " ".join(command)
    assert "readonly" in " ".join(command)


def test_timeout_kills_real_process(tmp_path):
    import sys

    with pytest.raises(RunStopped, match="timeout"):
        execute(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            tmp_path,
            lambda: None,
            0.1,
            {"PATH": os.environ["PATH"]},
        )


def test_output_tail_is_bounded(tmp_path):
    import sys

    code, output = execute(
        [sys.executable, "-c", "print('x'*200000)"],
        tmp_path,
        lambda: None,
        3,
        {"PATH": os.environ["PATH"]},
    )
    assert code == 0
    assert len(output.encode()) <= 32000
