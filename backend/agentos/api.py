import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import ExitStack, asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import text

from .graph import build_graph
from .ingestion import extract_upload
from .rag import Retrieval
from .security import authenticate, rate_limit, validate_configuration
from .store import Store
from .worker_lock import worker_lock

logging.basicConfig(level=logging.INFO, format="%(message)s")
tasks = set()


@asynccontextmanager
async def lifespan(app):
    validate_configuration()
    app.state.store = Store()
    app.state.rag = Retrieval(app.state.store)
    with ExitStack() as stack:
        stack.enter_context(worker_lock(app.state.store))
        async with checkpoint_context() as cp:
            app.state.graph = build_graph(app.state.store, app.state.rag, cp)
            await recover_jobs()
            dispatcher = asyncio.create_task(job_dispatcher())
            yield
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="AgentOS", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)


def identity(authorization: str = Header(default="")):
    principal = authenticate(authorization)
    rate_limit(app.state.store, principal)
    if "data:read" not in principal["scopes"]:
        raise HTTPException(403, "Workspace read scope required")
    return principal


def owned(run_id, user):
    rows = app.state.store.execute(
        "SELECT * FROM runs WHERE id=:id AND workspace=:w", dict(id=run_id, w=user["workspace"])
    )
    if not rows:
        raise HTTPException(404, "Run not found")
    return json.loads(rows[0]["state"])


def save(run_id, w, state):
    app.state.store.execute(
        "UPDATE runs SET state=:s WHERE id=:id AND workspace=:w",
        dict(id=run_id, w=w, s=json.dumps(state, default=str)),
    )


async def execute(run_id, w, input):
    config = {"configurable": {"thread_id": w + ":" + run_id}, "recursion_limit": 30}
    try:
        result = await asyncio.wait_for(app.state.graph.ainvoke(input, config), 180)
        snapshot = await app.state.graph.aget_state(config)
        status = (
            "awaiting_approval"
            if snapshot.interrupts
            else result.get("report", {}).get("status", "completed")
        )
        state = {**result, "status": status, "approval": [i.value for i in snapshot.interrupts]}
        state.pop("__interrupt__", None)
        save(run_id, w, state)
        logging.info(
            json.dumps(
                {"event": "run_finished", "run_id": run_id, "workspace": w, "status": status}
            )
        )
    except asyncio.CancelledError:
        # Shutdown leaves the persisted job recoverable; explicit cancel is handled by endpoint.
        raise
    except Exception as exc:
        save(run_id, w, {"status": "failed", "error": type(exc).__name__, "detail": str(exc)[:500]})


def launch(coro, name=None):
    task = asyncio.create_task(coro, name=name)
    tasks.add(task)
    task.add_done_callback(tasks.discard)


class TaskRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)
    workflow: Literal["auto", "business", "research", "operations"] = "auto"
    mode: Literal["demo", "openai", "anthropic"] = "demo"
    model: str | None = None
    memory_enabled: bool = True
    conversation: list[dict] = Field(default_factory=list, max_length=12)


class Decision(BaseModel):
    approve: bool
    proposal_id: str | None = Field(default=None, max_length=128)


class Document(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200000)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def config(user=Depends(identity)):
    return {
        "workspace": user["workspace"],
        "role": user["role"],
        "providers": ["demo"]
        + (["openai"] if os.getenv("OPENAI_API_KEY") else [])
        + (["anthropic"] if os.getenv("ANTHROPIC_API_KEY") else []),
        "embedding": app.state.rag.descriptor,
        "auth_mode": os.getenv("AUTH_MODE", "demo"),
        "capabilities": list(__import__("agentos.tools", fromlist=["CAPABILITIES"]).CAPABILITIES),
    }


@app.post("/demo/seed")
def seed(user=Depends(identity)):
    if user["role"] != "admin" or "admin" not in user["scopes"]:
        raise HTTPException(403)
    s = app.state.store
    s.seed(user["workspace"])
    exists = s.execute("SELECT id FROM documents WHERE workspace=:w", {"w": user["workspace"]})
    if not exists:
        app.state.rag.ingest(
            user["workspace"],
            "Demo operating policy",
            "Revenue rose after the launch of the enterprise subscription. Operational reports require manager approval. Inventory reorder threshold is 20 units. These are synthetic demo records.",
        )
    return {"seeded": True, "synthetic": True}


@app.post("/documents")
def document(body: Document, user=Depends(identity)):
    if "knowledge:write" not in user["scopes"]:
        raise HTTPException(403)
    return {"ids": app.state.rag.ingest(user["workspace"], body.source, body.content)}


@app.post("/documents/upload")
async def upload(file: UploadFile = File(...), user=Depends(identity)):
    if "knowledge:write" not in user["scopes"]:
        raise HTTPException(403)
    data = await file.read(5_000_001)
    if len(data) > 5_000_000:
        raise HTTPException(413, "5 MB maximum")
    try:
        content = await extract_upload(file.filename or "upload.txt", data)
        ids = await asyncio.to_thread(
            app.state.rag.ingest, user["workspace"], file.filename or "upload", content
        )
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ids": ids}


def check_model_choice(mode, model):
    """Clients may pick a model only from the operator's allowlist.

    A free-form model ID lets any editor select an arbitrarily expensive model. Local
    demos stay permissive; any shared deployment must configure ALLOWED_MODELS.
    """
    if mode == "demo" or not model:
        return
    configured = os.getenv("ALLOWED_MODELS", "").strip()
    if not configured:
        if os.getenv("DEPLOYMENT", "local") != "local":
            raise HTTPException(403, "Set ALLOWED_MODELS before accepting client model choices")
        return
    allowed = {m.strip() for m in configured.split(",") if m.strip()}
    if model not in allowed:
        raise HTTPException(403, "Model is not on the operator allowlist")


@app.post("/runs", status_code=202)
async def run(body: TaskRequest, user=Depends(identity)):
    if user["role"] not in {"admin", "editor"}:
        raise HTTPException(403)
    check_model_choice(body.mode, body.model)
    run_id = str(uuid.uuid4())
    w = user["workspace"]
    initial = {
        **body.model_dump(),
        "workspace": w,
        "run_id": run_id,
        "results": [],
        "events": [],
        "failures": 0,
        "scopes": user["scopes"],
    }
    with app.state.store.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO runs VALUES(:id,:w,:s,:t)"),
            dict(id=run_id, w=w, s=json.dumps({**initial, "status": "running"}), t=time.time()),
        )
        enqueue(conn, run_id, w, {"kind": "start", "state": initial})
    return {"id": run_id}


@app.get("/runs")
def history(user=Depends(identity)):
    return [
        {"id": r["id"], "created": r["created"], **json.loads(r["state"])}
        for r in app.state.store.execute(
            "SELECT * FROM runs WHERE workspace=:w ORDER BY created DESC", {"w": user["workspace"]}
        )
    ]


@app.get("/runs/{run_id}")
async def get_run(run_id: str, user=Depends(identity)):
    state = owned(run_id, user)
    if state["status"] == "running":
        snap = await app.state.graph.aget_state(
            {"configurable": {"thread_id": user["workspace"] + ":" + run_id}}
        )
        return {**state, **snap.values}
    return state


@app.post("/runs/{run_id}/approval", status_code=202)
async def approve(run_id: str, body: Decision, user=Depends(identity)):
    if user["role"] != "admin" or "admin" not in user["scopes"]:
        raise HTTPException(403, "Admin required")
    # Atomic claim prevents duplicate concurrent resumes.
    state = owned(run_id, user)
    if state["status"] != "awaiting_approval":
        raise HTTPException(409, "No pending approval")
    current = state.get("approval", [{}])[0].get("proposal", {}).get("id")
    if (
        body.proposal_id is not None or os.getenv("DEPLOYMENT", "local") != "local"
    ) and body.proposal_id != current:
        raise HTTPException(409, "Decision must identify the pending proposal")
    old = json.dumps(state, default=str)
    state["status"] = "running"
    with app.state.store.engine.begin() as c:
        from sqlalchemy import text

        result = c.execute(
            text("UPDATE runs SET state=:new WHERE id=:id AND workspace=:w AND state=:old"),
            dict(new=json.dumps(state), old=old, id=run_id, w=user["workspace"]),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Already resumed")
        enqueue(
            c,
            run_id,
            user["workspace"],
            {"kind": "approval", "approve": body.approve, "proposal_id": current},
        )
    return {"id": run_id}


@app.get("/experiments")
def experiments(user=Depends(identity)):
    return [
        json.loads(r["result"])
        for r in app.state.store.execute(
            "SELECT result FROM experiments WHERE workspace=:w ORDER BY created DESC",
            {"w": user["workspace"]},
        )
    ]


@app.post("/runs/{run_id}/resume", status_code=202)
async def resume(run_id: str, user=Depends(identity)):
    if user["role"] != "admin" or "admin" not in user["scopes"]:
        raise HTTPException(403)
    state = owned(run_id, user)
    if any(not task.done() and task.get_name() == run_id for task in tasks):
        raise HTTPException(409, "Already executing")
    if state["status"] in {"cancelled", "completed", "refused", "needs_clarification"}:
        raise HTTPException(409, "Run is terminal")
    if state["status"] == "awaiting_approval":
        raise HTTPException(409, "Use approval endpoint")
    snap = await app.state.graph.aget_state(
        {"configurable": {"thread_id": user["workspace"] + ":" + run_id}}
    )
    if not snap.next:
        raise HTTPException(409, "No interrupted execution to resume")
    with app.state.store.engine.begin() as conn:
        changed = conn.execute(
            text("UPDATE runs SET state=:new WHERE id=:id AND workspace=:w AND state=:old"),
            dict(
                new=json.dumps({**state, "status": "running"}),
                old=json.dumps(state),
                id=run_id,
                w=user["workspace"],
            ),
        )
        if changed.rowcount != 1:
            raise HTTPException(409, "Run changed")
        enqueue(conn, run_id, user["workspace"], {"kind": "resume"})
    return {"id": run_id}


@asynccontextmanager
async def checkpoint_context():
    url = os.getenv("CHECKPOINT_DATABASE_URL")
    if url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(url) as cp:
            await cp.setup()
            yield cp
    else:
        async with AsyncSqliteSaver.from_conn_string(
            os.getenv("CHECKPOINT_PATH", "checkpoints.db")
        ) as cp:
            yield cp


def enqueue(conn, run_id, w, payload):
    conn.execute(
        text("INSERT INTO jobs VALUES(:id,:w,:input,'queued',0,0)"),
        dict(
            id=run_id + ":" + str(uuid.uuid4()),
            w=w,
            input=json.dumps({"run_id": run_id, **payload}),
        ),
    )


async def recover_jobs():
    # Supported deployment is one scheduler per database; active processes may not share this queue.
    app.state.store.execute("UPDATE jobs SET status='queued' WHERE status='running'")


async def job_dispatcher():
    while True:
        rows = app.state.store.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 8"
        )
        for job in rows:
            payload = json.loads(job["input"])
            run_id = payload["run_id"]
            w = job["workspace"]
            if any(not t.done() and t.get_name() == run_id for t in tasks):
                continue
            from sqlalchemy import text

            with app.state.store.engine.begin() as c:
                result = c.execute(
                    text(
                        "UPDATE jobs SET status='running',lease=:lease,attempts=attempts+1 WHERE id=:id AND status='queued'"
                    ),
                    dict(id=job["id"], lease=time.time() + 240),
                )
                if result.rowcount != 1:
                    continue

            async def process(job=job, payload=payload, run_id=run_id, w=w):
                try:
                    cfg = {"configurable": {"thread_id": w + ":" + run_id}}
                    snapshot = await app.state.graph.aget_state(cfg)
                    pending = [i.value for i in snapshot.interrupts]
                    expected = payload.get("proposal_id")
                    if (
                        payload["kind"] == "approval"
                        and pending
                        and (
                            not expected
                            or not any(i.get("proposal", {}).get("id") == expected for i in pending)
                        )
                    ):
                        # Legacy or replayed decision: return the current proposal to the operator.
                        save(
                            run_id,
                            w,
                            {**snapshot.values, "status": "awaiting_approval", "approval": pending},
                        )
                    else:
                        argument = (
                            Command(resume=payload["approve"])
                            if payload["kind"] == "approval" and pending
                            else None
                            if snapshot.values
                            else payload.get("state")
                        )
                        await execute(run_id, w, argument)
                    app.state.store.execute(
                        "UPDATE jobs SET status='done' WHERE id=:id", {"id": job["id"]}
                    )
                except asyncio.CancelledError:
                    app.state.store.execute(
                        "UPDATE jobs SET status='queued' WHERE id=:id AND status='running'",
                        {"id": job["id"]},
                    )
                    raise

            launch(process(), run_id)
        await asyncio.sleep(0.2)


@app.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, user=Depends(identity)):
    if "action:write" not in user["scopes"]:
        raise HTTPException(403)
    state = owned(run_id, user)
    if state["status"] not in {"running", "awaiting_approval"}:
        raise HTTPException(409, "Execution is already terminal")
    for task in list(tasks):
        if task.get_name() == run_id:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    rows = app.state.store.execute(
        "SELECT id,input FROM jobs WHERE workspace=:w AND status IN ('queued','running')",
        {"w": user["workspace"]},
    )
    for row in rows:
        if json.loads(row["input"])["run_id"] == run_id:
            app.state.store.execute(
                "UPDATE jobs SET status='cancelled' WHERE id=:id", {"id": row["id"]}
            )
    save(run_id, user["workspace"], {**state, "status": "cancelled"})
    return {"status": "cancelled"}


@app.get("/runs/{run_id}/traces")
def traces(run_id: str, user=Depends(identity)):
    owned(run_id, user)
    return [
        {**row, "payload": json.loads(row["payload"])}
        for row in app.state.store.execute(
            "SELECT kind,payload,created FROM traces WHERE workspace=:w AND run_id=:r ORDER BY created",
            dict(w=user["workspace"], r=run_id),
        )
    ]


@app.get("/documents")
def documents(user=Depends(identity)):
    return app.state.store.execute(
        "SELECT id,source,digest,metadata FROM rag_sources WHERE workspace=:w",
        {"w": user["workspace"]},
    )


@app.delete("/documents/{document_id}")
def delete_document(document_id: str, user=Depends(identity)):
    if "knowledge:write" not in user["scopes"]:
        raise HTTPException(403)
    rows = app.state.store.execute(
        "SELECT source FROM rag_sources WHERE workspace=:w AND id=:id",
        dict(w=user["workspace"], id=document_id),
    )
    if not rows:
        raise HTTPException(404)
    app.state.rag.delete(user["workspace"], rows[0]["source"])
    return {"deleted": True}


@app.post("/documents/reindex")
async def reindex(user=Depends(identity)):
    if user["role"] != "admin" or "admin" not in user["scopes"]:
        raise HTTPException(403)
    return await asyncio.to_thread(app.state.rag.reindex, user["workspace"])


@app.delete("/memory/{memory_id}")
def forget(memory_id: str, user=Depends(identity)):
    if "knowledge:write" not in user["scopes"]:
        raise HTTPException(403)
    app.state.rag.forget(user["workspace"], memory_id)
    return {"deleted": True}


@app.get("/inbox")
def inbox(user=Depends(identity)):
    return [
        {"id": r["approval_id"], "tool": r["tool"], "result": json.loads(r["result"])}
        for r in app.state.store.execute(
            "SELECT approval_id,tool,result FROM effects WHERE workspace=:w ORDER BY created DESC",
            {"w": user["workspace"]},
        )
    ]


@app.get("/evaluations/retrieval")
def retrieval_evaluation(user=Depends(identity)):
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "evals" / "retrieval-heldout-results.json"
    if not path.exists():
        return {"source": "local_artifact", "data": None}
    return {"source": "bundled_measured_local_run", "data": json.loads(path.read_text())}


@app.get("/evaluations/live")
def live_evaluation(user=Depends(identity)):
    """Bundled frozen live-model results (summaries only; raw traces stay in the repo)."""
    from pathlib import Path

    folder = Path(__file__).resolve().parents[2] / "evals" / "results" / "live"
    rows = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        data = json.loads(path.read_text())
        if "summary" not in data:
            continue
        summary = {k: v for k, v in data["summary"].items() if k != "cases"}
        rows.append(
            {
                "file": path.name,
                "configuration": data["configuration"],
                "summary": summary,
                "cases": data["summary"].get("cases", {}),
            }
        )
    return {"source": "bundled_measured_runs", "results": rows}
