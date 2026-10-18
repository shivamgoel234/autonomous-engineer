import shutil
import time
from dataclasses import asdict

from .domain import PolicyError, RunStopped
from .providers import TOOLS, DemoProvider, OpenAIProvider
from .workspace import Workspace


class Engine:
    def __init__(self, settings, store, runner, shutting_down, provider_factory=None):
        self.settings = settings
        self.store = store
        self.runner = runner
        self.shutting_down = shutting_down
        self.provider_factory = provider_factory

    def execute(self, run_id):
        started = time.monotonic()
        deadline = started + self.settings.run_timeout
        run = self.store.run(run_id)
        project = self.store.project(run["project_id"])
        original = self.settings.data_dir / "projects" / project["id"]
        path = self.settings.data_dir / "runs" / run_id
        workspace = None

        def stop():
            if self.shutting_down.is_set():
                raise RunStopped("interrupted")
            if self.store.run(run_id)["cancel_requested"]:
                raise RunStopped("cancelled")
            if time.monotonic() >= deadline:
                raise RunStopped("timeout")

        def test(attempt):
            stop()
            self.store.update(run_id, status="testing")
            try:
                result = self.runner.run(
                    path, stop, min(self.settings.test_timeout, deadline - time.monotonic())
                )
            except RunStopped:
                raise
            except Exception as exc:
                raise RuntimeError("Sandbox runner failed") from exc
            current = self.store.run(run_id)
            self.store.update(
                run_id, tests=current["tests"] + [dict(attempt=attempt, **asdict(result))]
            )
            self.store.event(
                run_id,
                "test",
                f"Attempt {attempt}: {result.passed} passed, "
                f"{result.failed} failed, {result.errors} errors",
                asdict(result),
            )
            return result

        try:
            stop()
            if self.settings.runner == "trusted-demo" and project["kind"] not in {
                "demo:cart",
                "demo:slug",
                "demo:median",
            }:
                raise PolicyError("Local runner accepts bundled demo repositories only.")
            shutil.copytree(original, path)
            workspace = Workspace(path)
            self.store.event(run_id, "workspace", "Created an isolated repository copy")
            if self.provider_factory:
                provider = self.provider_factory(project)
            elif self.settings.provider == "demo":
                if not project["kind"].startswith("demo:"):
                    raise PolicyError("Demo provider only supports bundled examples.")
                provider = DemoProvider(project["kind"].split(":")[1])
            else:
                provider = OpenAIProvider(self.settings.api_key, self.settings.model)
            history = [dict(kind="task", data=dict(task=run["task"], files=workspace.files()))]
            result = test(0)
            self.store.event(run_id, "baseline", "Baseline captured before source changes")
            calls = input_tokens = output_tokens = 0
            for attempt in range(1, self.settings.max_attempts + 1):
                self.store.update(
                    run_id, status="repairing" if attempt > 1 else "planning", attempt=attempt
                )
                history.append(
                    dict(kind="attempt", data=dict(attempt=attempt, previous_test=asdict(result)))
                )
                planned = False
                while True:
                    stop()
                    if calls >= self.settings.max_tool_calls:
                        raise RunStopped("budget_exhausted")
                    self.store.update(run_id, status="repairing" if attempt > 1 else "implementing")
                    action = provider.next_action(history, deadline - time.monotonic())
                    stop()
                    calls += 1
                    input_tokens += action.input_tokens
                    output_tokens += action.output_tokens
                    self.store.update(
                        run_id,
                        tool_calls=calls,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                    if input_tokens + output_tokens > self.settings.max_tokens:
                        raise RunStopped("budget_exhausted")
                    schemas = {t["name"]: t["parameters"] for t in TOOLS}
                    if action.name not in schemas:
                        raise PolicyError("Unknown tool request.")
                    if set(action.arguments) != set(schemas[action.name]["properties"]):
                        raise PolicyError("Tool arguments do not match the contract.")
                    args = action.arguments
                    if action.name != "record_plan" and any(
                        not isinstance(value, str) or len(value.encode()) > 100000
                        for value in args.values()
                    ):
                        raise PolicyError("Tool arguments must be bounded strings.")
                    if action.name == "record_plan":
                        steps = args["steps"]
                        if (
                            not isinstance(steps, list)
                            or not 1 <= len(steps) <= 5
                            or any(not isinstance(s, str) or len(s) > 300 for s in steps)
                        ):
                            raise PolicyError("Plan must contain one to five short steps.")
                        self.store.update(run_id, plan=steps)
                        planned = True
                        observation = {"recorded": True}
                    elif not planned:
                        raise PolicyError("Record a plan before using repository tools.")
                    elif action.name == "read_file":
                        observation = workspace.read(args["path"])
                    elif action.name == "search_code":
                        observation = workspace.search(args["query"])
                    elif action.name == "apply_edit":
                        observation = workspace.edit(args["path"], args["old"], args["new"])
                    else:
                        observation = {"next": "controller will run tests"}
                    self.store.event(
                        run_id,
                        "tool",
                        action.name,
                        {"path": args.get("path"), "query": args.get("query")},
                    )
                    history.append(
                        dict(
                            kind="tool_result",
                            data=dict(
                                name=action.name,
                                arguments=args,
                                call_id=action.call_id,
                                result=observation,
                            ),
                        )
                    )
                    if action.name == "finish":
                        break
                result = test(attempt)
                stop()
                patch, changed = workspace.diff(original)
                self.store.update(run_id, diff=patch, changed_files=changed)
                if result.ok and changed:
                    self.store.update(
                        run_id,
                        status="awaiting_review",
                        elapsed_seconds=round(time.monotonic() - started, 3),
                    )
                    self.store.event(
                        run_id, "validated", "Acceptance tests passed; human review required"
                    )
                    return
                self.store.event(
                    run_id, "repair", "Verification failed or no source change; retry bounded"
                )
            self.store.update(
                run_id, status="failed_tests", error="No validated patch within three attempts."
            )
        except RunStopped as exc:
            self.store.update(run_id, status=exc.status, error=f"Run stopped: {exc.status}")
            self.store.event(run_id, exc.status, f"Run stopped: {exc.status}")
        except PolicyError as exc:
            self.store.update(run_id, status="policy_blocked", error=str(exc))
            self.store.event(run_id, "policy_blocked", str(exc))
        except Exception as exc:
            # Do not leak API headers, model payloads, or host paths in client-facing errors.
            status = "sandbox_error" if isinstance(exc, (OSError, RuntimeError)) else "model_error"
            self.store.update(run_id, status=status, error=f"{status}: {type(exc).__name__}")
            self.store.event(
                run_id, status, "Execution failed; check provider or sandbox configuration"
            )
        finally:
            self.store.update(run_id, elapsed_seconds=round(time.monotonic() - started, 3))
