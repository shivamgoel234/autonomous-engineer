import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    provider: str = "demo"
    runner: str = "docker"
    owner_token: str = ""
    reviewer_token: str = ""
    api_key: str = ""
    model: str = ""
    sandbox_image: str = "ase-sandbox:1"
    max_attempts: int = 3
    max_tool_calls: int = 18
    max_tokens: int = 60000
    run_timeout: int = 180
    test_timeout: int = 30
    queue_size: int = 8

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("ASE_DATA_DIR", "./data")).resolve(),
            provider=os.getenv("ASE_PROVIDER", "demo"),
            runner=os.getenv("ASE_RUNNER", "docker"),
            owner_token=os.getenv("ASE_OWNER_TOKEN", ""),
            reviewer_token=os.getenv("ASE_REVIEWER_TOKEN", ""),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", ""),
            sandbox_image=os.getenv("ASE_SANDBOX_IMAGE", "ase-sandbox:1"),
        )

    def validate(self):
        if len(self.owner_token) < 24:
            raise ValueError("Set ASE_OWNER_TOKEN to a random token of at least 24 characters.")
        if self.reviewer_token and (
            len(self.reviewer_token) < 24 or self.reviewer_token == self.owner_token
        ):
            raise ValueError("Reviewer token must be distinct and at least 24 characters.")
        if self.provider not in {"demo", "openai"} or self.runner not in {"docker", "trusted-demo"}:
            raise ValueError("Unsupported provider or runner.")
        if self.provider == "openai" and (not self.api_key or not self.model):
            raise ValueError("OpenAI mode requires OPENAI_API_KEY and OPENAI_MODEL.")
        if self.provider == "openai" and self.runner != "docker":
            raise ValueError("LLM-generated code requires Docker. Local execution is demo-only.")
