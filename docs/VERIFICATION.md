# Verification record

Verified on 7 October 2026 using Python 3.12.14 and Node.js 24.19.0 on Linux.

| Check | Result |
|---|---|
| Backend policy, workflow, adapter, and process tests | 37 passed |
| Frontend transport and interaction tests | 3 passed |
| Ruff checks and Python formatting | Passed |
| Strict TypeScript compilation and Vite production build | Passed |
| Three scripted fixtures through the trusted local runner | 3/3 resolved in two repair attempts each |
| Final acceptance counts | Checkout: 5; slug: 4; median: 4; no failures |
| Real Uvicorn HTTP workflow: submit, observe, review, export | Passed |
| Exported checkout patch: `git apply --check` | Passed against matching fixture |
| Docker CLI restrictions/environment contract | Tested with a mocked execution boundary |
| Actual Docker containers | Not executed here; no Docker daemon/CLI available |
| Live OpenAI inference | Not executed; no user API credentials configured |
| Visual browser layout | Not verified; browser binary unavailable and remote browser could not reach local service |

CI is configured to build the sandbox image and execute the real Docker fixture benchmark after the source is pushed to GitHub. No hosted CI execution is claimed.

The 3/3 fixture result is scripted integration evidence, not an AI-model accuracy benchmark. Full structured fixture results are in `evaluation-local.json`.
