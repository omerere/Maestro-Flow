"""
FastAPI route definitions.

This module is strictly responsible for HTTP routing logic and flow
traversal helpers. It registers all endpoints on an ``APIRouter`` that
is included by ``app/main.py``.
"""

from typing import Any, Callable, Dict, List

from fastapi import APIRouter, Body

from app.api.schemas import (
    CreateUserRequest,
    CreateUserResponse,
    CurrentPositionResponse,
    FlowResponse,
    StatusResponse,
    StepSummary,
    TaskCompleteResponse,
    TaskSummary,
    DYNAMIC_TASK_EXAMPLES,
)
from app.core.engine import WorkflowEngine
from app.core.flow_config import (
    FLOW_STEPS,
    FLOW_TASKS,
    STARTING_STEP_ID,
)
from app.core.store import user_store
from app.models.schemas import TaskPayload, StepNode
router = APIRouter()

# ---------------------------------------------------------------------------
# Dependency: engine instance shared with main.py via import
# ---------------------------------------------------------------------------
# The engine is instantiated in main.py and imported here so that both the
# exception handlers (registered on the FastAPI app) and the route handlers
# share the same object without creating a second graph instance.
# We import it lazily inside functions to avoid a circular import at module
# load time.


def _get_engine() -> "WorkflowEngine":
    from app.main import engine  # noqa: PLC0415 — intentional lazy import

    return engine


# ---------------------------------------------------------------------------
# Flow traversal helpers
# ---------------------------------------------------------------------------


def _evaluate_condition(
    condition: Callable | None, user_context: Dict[str, Any]
) -> bool:
    """
    Safely evaluate an outcome condition against accumulated user context.

    Passes ``user_context`` as both the payload and context arguments that
    condition callables expect, since the accumulated context absorbs all
    previous task payloads. Returns ``False`` on any exception so that
    unevaluable conditions (e.g. missing keys for future steps) default
    to no-match.

    Args:
        condition: A condition callable ``(payload, context) -> bool``, or
                   ``None`` for an unconditional (always-matching) outcome.
        user_context: The user's accumulated context dict.

    Returns:
        ``True`` if the condition matches (or is unconditional), ``False``
        otherwise.
    """
    if condition is None:
        return True
    try:
        return bool(condition(user_context, user_context))
    except Exception:
        return False


def _resolve_step_tasks(
    step: StepNode, 
    ctx: Dict[str, Any]
) -> tuple[List[TaskSummary], str | None]:
    """
    Traverses the tasks within a single step based on the user's context.
    
    Returns:
        A tuple containing:
        - A list of ordered TaskSummary objects within the current step.
        - An optional step ID to jump to (if a task triggered a Fast Track), 
          or None if normal flow continues.
    """
    tasks: List[TaskSummary] = []
    current_task_id: str | None = step.first_task_id
    visited_tasks: set = set()
    jump_to_step_id: str | None = None

    #While there are still tasks within the step we haven't visited
    while current_task_id and current_task_id not in visited_tasks:
        visited_tasks.add(current_task_id)
        task = FLOW_TASKS[current_task_id]
        tasks.append(TaskSummary(id=task.id, name=task.name))

        next_task_id: str | None = None
        #For each of the possible outcomes to this task
        for outcome in task.next_tasks:
            if not _evaluate_condition(outcome.condition, ctx):
                continue
            if (
                #if the condition was evaluated to terminal outcome:continue, 
                # which will exit the outerloop as well in the next iteration
                outcome.next_task_id is None
                and outcome.next_step_id is None
                and outcome.status is not None
            ):
                continue  
            
            next_task_id = outcome.next_task_id
            jump_to_step_id = outcome.next_step_id 
            break
        
        current_task_id = next_task_id
        
        # If a fast-track step jump was triggered, immediately exit the task loop
        if jump_to_step_id:
            break

    return tasks, jump_to_step_id


def _build_ordered_flow(
    user_context: Dict[str, Any] | None = None,
    user_id: str | None = None,
) -> FlowResponse:
    """
    Generates a linear, user-specific roadmap by traversing the workflow graph.

    This function simulates the user's journey based on their current context. 
    It evaluates branch conditions to flatten the graph into an ordered list 
    of steps and tasks for the frontend.    
    """
    ctx: Dict[str, Any] = user_context if user_context is not None else {}
    ordered_steps: List[StepSummary] = []
    current_step_id: str | None = STARTING_STEP_ID
    visited_steps: set = set()

    while current_step_id and current_step_id not in visited_steps:
        visited_steps.add(current_step_id)
        step = FLOW_STEPS[current_step_id]

        # Delegate task traversal to the helper function
        tasks, jump_to_step_id = _resolve_step_tasks(step, ctx)
        ordered_steps.append(StepSummary(id=step.id, name=step.name, tasks=tasks))

        # Advance to the next step
        if jump_to_step_id:
            # Execute the fast-track jump captured from the task level
            current_step_id = jump_to_step_id
        else:
            # Fallback to standard step-level routing
            next_step_id: str | None = None
            for outcome in step.next_steps:
                if not _evaluate_condition(outcome.condition, ctx):
                    continue
                if outcome.next_step_id is None and outcome.status is not None:
                    continue  # Skip terminal outcome
                next_step_id = outcome.next_step_id
                break
            current_step_id = next_step_id

    return FlowResponse(
        user_id=user_id,
        total_steps=len(ordered_steps),
        ordered_steps=ordered_steps,
    )

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/users", response_model=CreateUserResponse, status_code=201)
async def create_user(body: CreateUserRequest) -> CreateUserResponse:
    """
    Register a new applicant and place them at the start of the workflow.

    Args:
        body: JSON object containing the applicant's ``email``.

    Returns:
        The generated ``user_id`` for subsequent requests.
    """
    user_id = user_store.create_user(email=body.email)
    return CreateUserResponse(user_id=user_id)


@router.get("/flow", response_model=FlowResponse)
async def get_flow(user_id: str | None = None) -> FlowResponse:
    """
    Return the admissions workflow as an ordered list of steps and tasks.

    When ``user_id`` is omitted the endpoint returns the global default
    (happy-path) flow. When ``user_id`` is provided the flow is tailored
    to that user: conditions are evaluated against their accumulated context
    so that conditional branches (e.g. a "second chance" task) only appear
    for users to whom they apply.

    Args:
        user_id: Optional query parameter. If supplied, the user must exist
                 in the store or a 404 is returned.

    Returns:
        A FlowResponse containing an optional ``user_id``, ``total_steps``
        (int), and ``ordered_steps`` (list of StepSummary, each containing
        an ordered ``tasks`` list).

    Raises:
        404: If ``user_id`` is provided but not found in the store.
    """
    if user_id is not None:
        user = user_store.get_user(user_id)
        return _build_ordered_flow(user_context=user.context, user_id=user_id)
    return _build_ordered_flow(user_context={})


@router.get("/users/{user_id}/current", response_model=CurrentPositionResponse)
async def get_current_position(user_id: str) -> CurrentPositionResponse:
    """
    Return the applicant's current position in the workflow graph.

    Args:
        user_id: The applicant's unique identifier.

    Returns:
        The IDs of the StepNode and TaskNode the applicant must complete next.

    Raises:
        404: If the user_id is not registered in the store.
    """
    user = user_store.get_user(user_id)
    return CurrentPositionResponse(
        current_step_id=user.current_step_id,
        current_task_id=user.current_task_id,
    )


@router.put("/tasks/complete", response_model=TaskCompleteResponse)
async def complete_task(body: TaskPayload = Body(..., openapi_examples=DYNAMIC_TASK_EXAMPLES)) -> TaskCompleteResponse:
    """
    Webhook: submit a completed task and advance the applicant's journey.

    Validates the payload against the current TaskNode's validator,
    evaluates routing Outcomes, persists the updated UserState, and
    returns the full updated state.

    Args:
        body: A TaskPayload containing the applicant's ``user_id``,
              the ``step_id`` and ``task_id`` being submitted, and
              the raw ``payload`` dict from the external system.

    Returns:
        The updated UserState serialised as a JSON object.

    Raises:
        400: If the payload fails validation or targets the wrong task.
        404: If the user_id is not registered in the store.
        422: If graph routing cannot be resolved.
    """
    user = user_store.get_user(body.user_id)
    updated_user = _get_engine().process_webhook(payload=body, user=user)
    user_store.save_user(updated_user)
    return TaskCompleteResponse(
        user_id=updated_user.user_id,
        current_step_id=updated_user.current_step_id,
        current_task_id=updated_user.current_task_id,
        context=updated_user.context,
        status=updated_user.status,
    )


@router.get("/users/{user_id}/status", response_model=StatusResponse)
async def get_status(user_id: str) -> StatusResponse:
    """
    Return the applicant's current journey status.

    Args:
        user_id: The applicant's unique identifier.

    Returns:
        The journey ``status``: one of ``"in_progress"``, ``"accepted"``,
        or ``"rejected"``.

    Raises:
        404: If the user_id is not registered in the store.
    """
    user = user_store.get_user(user_id)
    return StatusResponse(status=user.status)
