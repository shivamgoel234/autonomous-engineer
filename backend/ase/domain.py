from dataclasses import dataclass
from typing import Callable, Protocol

TERMINAL = frozenset(
    {
        "awaiting_review",
        "approved",
        "rejected",
        "failed_tests",
        "cancelled",
        "timeout",
        "budget_exhausted",
        "model_error",
        "sandbox_error",
        "policy_blocked",
        "interrupted",
    }
)


class PolicyError(ValueError):
    """A requested operation crosses an explicit application boundary."""


class RunStopped(Exception):
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


@dataclass
class TestResult:
    exit_code: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    output: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.passed > 0 and self.failed == 0 and self.errors == 0


@dataclass
class Action:
    name: str
    arguments: dict
    call_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class Provider(Protocol):
    def next_action(self, history: list[dict], remaining: float) -> Action: ...


class Runner(Protocol):
    def run(self, workspace, stop: Callable[[], None], timeout: float) -> TestResult: ...
