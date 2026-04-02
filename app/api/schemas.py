"""
Presentation models (DTOs) for the API layer.

This module contains all Pydantic models that define the JSON contracts
for the HTTP endpoints declared in ``app.api.endpoints``. These are pure
Data Transfer Objects.

"""

from typing import Any, Dict, List

from pydantic import BaseModel

from app.core.flow_config import FLOW_TASKS, FLOW_STEPS


class CreateUserRequest(BaseModel):
    """Body accepted by POST /users."""

    email: str


class CreateUserResponse(BaseModel):
    """Body returned by POST /users."""

    user_id: str


class TaskSummary(BaseModel):
    """A single task entry inside an ordered step."""

    id: str
    name: str


class StepSummary(BaseModel):
    """A single step entry in the ordered flow response."""

    id: str
    name: str
    tasks: List[TaskSummary]


class FlowResponse(BaseModel):
    """Body returned by GET /flow."""

    user_id: str | None = None
    total_steps: int
    ordered_steps: List[StepSummary]


class CurrentPositionResponse(BaseModel):
    """Body returned by GET /users/{user_id}/current."""

    current_step_id: str
    current_task_id: str
    


class StatusResponse(BaseModel):
    """Body returned by GET /users/{user_id}/status."""

    status: str


class TaskCompleteResponse(BaseModel):
    """Body returned by PUT /tasks/complete.

    Mirrors the full updated UserState so callers can react to position
    changes and terminal statuses (``"accepted"`` / ``"rejected"``) without
    issuing a follow-up GET request.
    """

    user_id: str
    current_step_id: str
    current_task_id: str
    context: Dict[str, Any]
    status: str


# ---------------------------------------------------------------------------
# Dynamic Swagger UI Examples Generation
# ---------------------------------------------------------------------------


def _build_task_examples() -> Dict[str, Any]:
    """
    Build the OpenAPI ``openapi_examples`` dict for the PUT /tasks/complete
    endpoint by traversing the live workflow graph.

    Starts at each StepNode's ``first_task_id`` and follows intra-step
    ``next_task_id`` edges, collecting each TaskNode's ``example_payload``
    along the way. The result is a mapping of task ID → OpenAPI example object
    ready to be passed to FastAPI's ``Body(..., openapi_examples=...)``.

    Returns:
        A dict whose keys are task IDs (plus a ``"default"`` placeholder) and
        whose values are OpenAPI example objects (``summary`` + ``value``).
    """
    examples: Dict[str, Any] = {
        "default": {
            "summary": "--- SELECT A TASK EXAMPLE ---",
            "value": {
                "user_id": "ENTER_USER_ID",
                "step_id": "SELECT_STEP",
                "task_id": "SELECT_TASK",
                "payload": {},
            },
        }
    }

    for step_id, step_node in FLOW_STEPS.items():
        current_task_id: str | None = step_node.first_task_id
        visited_in_step: set = set()

        while current_task_id and current_task_id not in visited_in_step:
            visited_in_step.add(current_task_id)
            task_node = FLOW_TASKS.get(current_task_id)

            if task_node and task_node.example_payload is not None:
                examples[current_task_id] = {
                    "summary": task_node.name,
                    "value": {
                        "user_id": "YOUR_USER_ID_HERE",
                        "step_id": step_id,
                        "task_id": current_task_id,
                        "payload": task_node.example_payload,
                    },
                }
                # Advance only along intra-step edges.
                next_id: str | None = None
                for outcome in task_node.next_tasks:
                    if outcome.next_task_id:
                        next_id = outcome.next_task_id
                        break
                current_task_id = next_id
            else:
                current_task_id = None

    return examples


DYNAMIC_TASK_EXAMPLES: Dict[str, Any] = _build_task_examples()