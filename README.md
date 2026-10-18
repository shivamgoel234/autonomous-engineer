# Autonomous Software Engineer / Forge

A Python repository agent that inspects source, proposes exact edits, executes acceptance tests, repairs failures within a budget, and produces a patch for human review. React + TypeScript, FastAPI, SQLite, Docker, and one explicit Python workflow.

**Start learning:** [Build from scratch guide](docs/BUILD_FROM_SCRATCH.md). The guide explains setup, file-writing order, architecture, every module, debugging, trade-offs, and interview preparation. Its appendix includes the complete handwritten source.

## Scope

Supports small UTF-8 Python repositories with `src/` and `tests/` at the ZIP root; dependencies must already exist in the sandbox image. Existing Python files under `src/` can be edited. Acceptance tests and configuration are protected. Original repositories stay intact. Approval records a human decision; the user applies the exported patch manually.

Three modes:

| Mode | Provider | Test runner | Use |
|---|---|---|---|
| Learning demo | Scripted fixtures | Trusted local process | No key or Docker required; bundled fixtures only |
| Docker demo | Scripted fixtures | Restricted container | Learn isolation using the same three examples |
| Real agent | OpenAI Responses API | Restricted container | Upload a supported source ZIP and submit a task |

The demo is **not AI**. It deliberately proposes an incomplete first repair and a correct second repair, while real pytest tests determine the result. Real OpenAI tasks require an API key, a tool-calling model available to your account, and Docker. No live provider accuracy claims are made.

## Run locally

Use Python 3.12 and Node.js 22 or newer. Windows users can follow the PowerShell instructions in the guide; WSL2 is the recommended environment for Docker execution.

From this directory on Linux/macOS/WSL:

```bash
bash scripts/setup.sh
```

Terminal 1, project root:

```bash
export ASE_OWNER_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Copy this token into the application's connect form; keep it private.
printf '%s\n' "$ASE_OWNER_TOKEN"
export ASE_PROVIDER=demo
export ASE_RUNNER=trusted-demo
.venv/bin/uvicorn ase.main:app --host 127.0.0.1 --port 8000
```

Terminal 2, project root:

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`. Connect, choose **Checkout total**, start the run, inspect **Test results** and **Patch diff**, approve, and download the patch. Tokens remain in browser memory. Reconnecting is required after a refresh.

## Enable Docker

```bash
docker build -t ase-sandbox:1 sandbox
export ASE_RUNNER=docker
.venv/bin/uvicorn ase.main:app --host 127.0.0.1 --port 8000
```

Set exports before starting the server. Stop an already running server with Ctrl+C first. Only one Uvicorn worker is supported. Never start multiple API processes against the same data directory.

## Enable real model calls

Keep the owner token set, build the sandbox image, and set these in Terminal 1:

```bash
export ASE_PROVIDER=openai
export ASE_RUNNER=docker
# Replace these locally; never commit a key.
export OPENAI_API_KEY='your-private-key'
export OPENAI_MODEL='your-tool-calling-model-id'
.venv/bin/uvicorn ase.main:app --host 127.0.0.1 --port 8000
```

Upload a source-only ZIP containing `src/` and `tests/` directly, without an enclosing folder, caches, hidden files, secrets, or dependencies. The sandbox image includes Python, pytest, and FastAPI. It does not install uploaded requirements. `examples/checkout.zip` provides a supported input fixture.

## Verify

```bash
bash scripts/check.sh
.venv/bin/python scripts/evaluate.py --output docs/evaluation-local.json
.venv/bin/python scripts/evaluate.py --docker --output docs/evaluation-docker.json
```

The second benchmark needs a Docker daemon and the built image. CI runs backend tests, frontend tests/build, and the Docker benchmark. The checked-in result describes three **scripted integration fixtures**, not a general AI benchmark.

## Design and limits

- Authenticated owner and optional reviewer roles; atomic review and idempotent run creation.
- One bounded worker thread; persistent status and event history; abandoned runs become interrupted on restart.
- Three attempts, 18 tool calls, 60,000 aggregate reported tokens, 180-second run budget, 30-second test budget.
- ZIP limits: 2 MB expanded source, 100 KB/file, 150 archive entries. At most five source files changed.
- Docker: network disabled, read-only filesystem/source mount, non-root user, dropped capabilities, CPU/memory/PID limits, 64 MB temporary filesystem.
- No shell tool, test edits, package installation, deletion, automatic git push, merge, or deployment.
- Tests are evidence, not proof of semantic correctness. Malicious Python can try to falsify test reporting; this is a controlled developer tool, not a hardened public service.
- Docker is a shared-kernel boundary. A public arbitrary-code service needs dedicated execution infrastructure and further security review.
- SQLite and filesystem storage have no automatic retention or distributed recovery. Preserve the data directory for history; plan cleanup and backups before extended use.
- SSE provides the timeline; polling updates the run summary. API `/docs` provides interactive OpenAPI documentation.

This is a complete, production-oriented learning implementation of the brief's core workflow, with selected reliability and review features. PostgreSQL/Redis, LangGraph, GitHub PR automation, MCP, semantic search, and distributed tenancy are extension work, not hidden placeholders.
