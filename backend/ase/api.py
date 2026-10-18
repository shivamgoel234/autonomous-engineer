import asyncio
import hmac
import json
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .domain import TERMINAL, PolicyError
from .service import Overloaded, Service
from .store import Store
from .workspace import MAX_REPOSITORY, Workspace


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=32, max_length=32)
    task: str = Field(min_length=10, max_length=3000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]


def create_app(settings=None, runner=None, provider_factory=None):
    settings = settings or Settings.from_env()
    settings.validate()
    store = Store(settings.data_dir / "ase.sqlite3")
    service = Service(settings, store, runner, provider_factory)
    submissions = deque()
    rate_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        service.start()
        yield
        await asyncio.to_thread(service.close)

    app = FastAPI(title="Autonomous Software Engineer", version="1.0.0", lifespan=lifespan)
    app.state.store, app.state.service = store, service

    def role(authorization: str = Header(default="")):
        token = authorization.removeprefix("Bearer ")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        if hmac.compare_digest(token.encode(), settings.owner_token.encode()):
            return "owner"
        if settings.reviewer_token and hmac.compare_digest(
            token.encode(), settings.reviewer_token.encode()
        ):
            return "reviewer"
        raise HTTPException(401, "Invalid token")

    def owner(actor=Depends(role)):
        if actor != "owner":
            raise HTTPException(403, "Owner role required")
        return actor

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Resource not found"})

    @app.exception_handler(FileNotFoundError)
    async def file_not_found(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "File not found"})

    @app.exception_handler(PolicyError)
    async def blocked(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def conflict(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/api/v1/health")
    def health(actor=Depends(role)):
        return dict(
            status="ok",
            provider=settings.provider,
            runner=settings.runner,
            role=actor,
            limits=dict(attempts=settings.max_attempts, tool_calls=settings.max_tool_calls),
        )

    @app.get("/api/v1/projects")
    def projects(actor=Depends(role)):
        return store.projects()

    @app.post("/api/v1/projects/demo/{scenario}", status_code=201)
    def demo(scenario: str, actor=Depends(owner)):
        return service.demo(scenario)

    @app.post("/api/v1/projects/upload", status_code=201)
    async def upload(request: Request, name: str = "Python repository", actor=Depends(owner)):
        if not 1 <= len(name) <= 80:
            raise HTTPException(422, "Name must be 1..80 characters")
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > MAX_REPOSITORY:
                raise HTTPException(413, "Archive exceeds 2 MB")
        return await asyncio.to_thread(service.upload, name, bytes(payload))

    @app.get("/api/v1/projects/{project_id}/files")
    def files(project_id: str, actor=Depends(role)):
        store.project(project_id)
        return Workspace(settings.data_dir / "projects" / project_id).files()

    @app.get("/api/v1/projects/{project_id}/file")
    def file(project_id: str, path: str, actor=Depends(role)):
        store.project(project_id)
        return {
            "path": path,
            "content": Workspace(settings.data_dir / "projects" / project_id).read(path),
        }

    @app.get("/api/v1/runs")
    def runs(actor=Depends(role)):
        return store.runs()

    @app.post("/api/v1/runs", status_code=202)
    def submit(
        body: RunRequest,
        idempotency_key: str = Header(min_length=8, max_length=100),
        actor=Depends(owner),
    ):
        with rate_lock:
            current = time.monotonic()
            while submissions and current - submissions[0] > 60:
                submissions.popleft()
            if len(submissions) >= 10:
                raise HTTPException(429, "At most ten run submissions per minute")
            submissions.append(current)
        try:
            run, _ = service.submit(body.project_id, body.task, idempotency_key)
        except Overloaded as exc:
            raise HTTPException(503, str(exc)) from exc
        return run

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str, actor=Depends(role)):
        return store.run(run_id)

    @app.post("/api/v1/runs/{run_id}/cancel", status_code=202)
    def cancel(run_id: str, actor=Depends(owner)):
        store.cancel(run_id)
        return {"requested": True}

    @app.post("/api/v1/runs/{run_id}/review")
    def review(run_id: str, body: ReviewRequest, actor=Depends(role)):
        return store.review(run_id, body.decision, actor)

    @app.get("/api/v1/runs/{run_id}/diff", response_class=PlainTextResponse)
    def diff(run_id: str, actor=Depends(role)):
        return store.run(run_id)["diff"]

    @app.get("/api/v1/runs/{run_id}/patch", response_class=PlainTextResponse)
    def patch(run_id: str, actor=Depends(role)):
        item = store.run(run_id)
        if item["status"] != "approved":
            raise HTTPException(409, "Approve the validated patch before export")
        return PlainTextResponse(
            item["diff"], headers={"Content-Disposition": 'attachment; filename="agent.patch"'}
        )

    @app.get("/api/v1/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = 0, actor=Depends(role)):
        store.run(run_id)
        try:
            cursor = max(after, int(request.headers.get("Last-Event-ID", "0")))
        except ValueError as exc:
            raise HTTPException(422, "Invalid event cursor") from exc

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                batch = await asyncio.to_thread(store.events, run_id, cursor)
                for event in batch:
                    cursor = event["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
                if (await asyncio.to_thread(store.run, run_id))["status"] in TERMINAL and len(
                    batch
                ) < 100:
                    yield "event: done\ndata: {}\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
