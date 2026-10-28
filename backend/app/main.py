from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse

from .config import ROOT, Settings
from .database import Store
from .intake import MAX_TOTAL_BYTES, import_archive, import_directory
from .middleware import RequestBodyLimit
from .providers import AIProvider, OllamaProvider
from .report import render_report
from .sandbox import DockerSandbox
from .schemas import DirectoryRequest, InvestigationRequest
from .workflow import TERMINAL, Workflow


def create_app(settings: Settings | None = None, provider: AIProvider | None = None, sandbox: DockerSandbox | None = None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.data_dir)
    provider = provider or OllamaProvider(settings)
    sandbox = sandbox or DockerSandbox(settings.docker_image, settings.test_timeout)
    workflow = Workflow(settings, store, provider, sandbox)
    tasks: set[asyncio.Task] = set()

    def launch(coroutine: object) -> None:
        task = asyncio.create_task(coroutine)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # A process restart cannot silently resume partially approved workflows.
        for item in store.list():
            if item["status"] not in TERMINAL:
                store.update(item["id"], status="interrupted", summary="Backend restarted during investigation; start a new investigation", error="Interrupted by process restart")
                store.emit(item["id"], "interrupted", "Backend restarted; automatic resumption is disabled")
        yield
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        store.engine.dispose()

    app = FastAPI(title="RootCause AI", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.workflow, app.state.tasks = store, workflow, tasks
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 4173, 8000)}
    app.add_middleware(CORSMiddleware, allow_origins=sorted(origins), allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Last-Event-ID"])
    app.add_middleware(RequestBodyLimit, max_bytes=MAX_TOTAL_BYTES + 1_000_000)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in origins:
                return PlainTextResponse("Untrusted browser origin", status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return PlainTextResponse("Cross-site requests are not allowed", status_code=403)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_TOTAL_BYTES + 1_000_000):
            return PlainTextResponse("Request body exceeds import limit", status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def get_item(identity: str) -> dict:
        if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise HTTPException(404, "Investigation not found")
        item = store.get(identity)
        if not item:
            raise HTTPException(404, "Investigation not found")
        return item

    @app.get("/api/health")
    async def health():
        ai, runner = await asyncio.gather(provider.health(), sandbox.health())
        runner = {**runner, "error": runner.get("reason") or runner.get("error")}
        return {"status": "ready" if ai["available"] and runner["available"] else "degraded", "ai": ai, "sandbox": runner}

    @app.get("/api/projects")
    async def projects():
        return store.projects()

    async def import_project(source: Path | bytes, name: str = "project.zip", demo: bool = False) -> dict:
        identity = uuid4().hex
        destination = settings.projects_dir / identity / "source"
        try:
            if isinstance(source, bytes):
                metadata = await asyncio.to_thread(import_archive, source, destination, name)
            else:
                roots = [ROOT / "samples"] if demo else settings.import_roots
                metadata = await asyncio.to_thread(import_directory, source, destination, roots)
            return store.add_project(identity, metadata["name"], metadata["file_count"])
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/projects/directory", status_code=201)
    async def directory(body: DirectoryRequest):
        return await import_project(Path(body.path))

    @app.post("/api/projects/archive", status_code=201)
    async def archive(file: UploadFile = File(...)):
        try:
            content = await file.read(MAX_TOTAL_BYTES + 1)
            if len(content) > MAX_TOTAL_BYTES:
                raise HTTPException(413, "Archive exceeds the 32 MiB limit")
            return await import_project(content, file.filename or "project.zip")
        finally:
            await file.close()

    @app.post("/api/demo", status_code=201)
    async def demo():
        return await import_project(ROOT / "samples" / "order-service", demo=True)

    @app.get("/api/investigations")
    async def investigations():
        return store.list()

    @app.post("/api/investigations", status_code=202)
    async def start(body: InvestigationRequest):
        project = store.project(body.project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        active = sum(not task.done() for task in tasks)
        if active >= 8:
            raise HTTPException(429, "Investigation queue is full; wait for active work to finish")
        identity = uuid4().hex
        store.create(identity, project)
        store.emit(identity, "queued", "Investigation queued")
        launch(workflow.investigate(identity, body.logs))
        return store.get(identity)

    @app.get("/api/investigations/{identity}")
    async def investigation(identity: str):
        return get_item(identity)

    @app.post("/api/investigations/{identity}/approve", status_code=202)
    async def approve(identity: str):
        get_item(identity)
        try:
            await workflow.decide(identity, True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        launch(workflow.verify(identity))
        return store.get(identity)

    @app.post("/api/investigations/{identity}/reject")
    async def reject(identity: str):
        get_item(identity)
        try:
            await workflow.decide(identity, False)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return store.get(identity)

    @app.get("/api/investigations/{identity}/events")
    async def events(identity: str, request: Request, after: int = 0):
        get_item(identity)
        try:
            cursor = max(0, after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor")

        async def stream():
            nonlocal cursor
            heartbeat = 0
            while not await request.is_disconnected():
                for item in store.events(identity, cursor):
                    cursor = item["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(item)}\n\n"
                status = store.get(identity, include_events=False)["status"]
                if status in TERMINAL:
                    yield "event: done\ndata: {}\n\n"
                    break
                heartbeat += 1
                if heartbeat % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Connection": "keep-alive"})

    @app.get("/api/investigations/{identity}/report")
    async def report(identity: str):
        return PlainTextResponse(render_report(get_item(identity)), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="rootcause-{identity[:8]}.md"'})

    return app


app = create_app()
