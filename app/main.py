"""
FastAPI application entry point.

Responsible for three concerns only:
  1. Instantiating the FastAPI application.
  2. Instantiating the WorkflowEngine (shared with endpoints via import).
  3. Registering application-level exception handlers.

All route definitions live in ``app.api.endpoints`` and are wired in via
``app.include_router``.

Run with:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from contextlib import asynccontextmanager

from app.api.endpoints import router as api_router
from app.core.engine import (
    NoMatchingOutcomeError,
    NodeNotFoundError,
    WorkflowEngine,
    WorkflowEngineError,
)
from app.core.flow_config import FLOW_STEPS, FLOW_TASKS
from app.core.store import UserNotFoundError

# ---------------------------------------------------------------------------
# Application instantiation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Maestro-Flow",
    description="Dynamic workflow engine for the Masterschool admissions system.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Core component — shared with endpoints.py via `from app.main import engine`
# ---------------------------------------------------------------------------

engine = WorkflowEngine(steps=FLOW_STEPS, tasks=FLOW_TASKS)

# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(UserNotFoundError)
async def user_not_found_handler(request: Request, exc: UserNotFoundError) -> JSONResponse:
    """Return HTTP 404 when a requested user_id is absent from the store."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Return HTTP 400 for validation failures and mismatched task/step submissions."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(NodeNotFoundError)
async def node_not_found_handler(request: Request, exc: NodeNotFoundError) -> JSONResponse:
    """Return HTTP 422 when a task or step ID cannot be resolved in the engine registry."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NoMatchingOutcomeError)
async def no_matching_outcome_handler(
    request: Request, exc: NoMatchingOutcomeError
) -> JSONResponse:
    """Return HTTP 422 when the routing graph cannot resolve a path for the applicant."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(WorkflowEngineError)
async def workflow_engine_error_handler(
    request: Request, exc: WorkflowEngineError
) -> JSONResponse:
    """Return HTTP 500 as a catch-all for any unhandled WorkflowEngineError subclass."""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Router 
# ---------------------------------------------------------------------------

app.include_router(api_router)

@app.get("/", include_in_schema=False)
def redirect_to_docs():
    return RedirectResponse(url="/docs")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    
    Prints a clear, entry point URL for developers 
    running the application locally or via Docker.
    """
    print("\n" + "="*60)
    print("🚀 Maestro-Flow Engine is Live!")
    print("📝 Interactive API Documentation: http://localhost:8000/docs")
    print("="*60 + "\n")
    yield

app = FastAPI(
    title="Maestro-Flow",
    lifespan=lifespan
)