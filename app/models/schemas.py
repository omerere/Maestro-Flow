"""
Pydantic data models for the Maestro-Flow workflow engine.

Defines the core graph primitives (Outcome, TaskNode, StepNode),
the mutable user-journey state (UserState), and the incoming
webhook contract (TaskPayload).
"""

from typing import Any, Callable, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Outcome(BaseModel):
    """
    Represents a typed, conditional edge in the workflow graph.

    An Outcome is evaluated by the engine to determine where a user
    travels after completing a task or step. Routing destinations are
    type-segregated into three mutually exclusive fields so the engine
    never has to infer destination type from a bare string:

      - ``next_task_id``  — advance to a specific TaskNode (intra-step).
      - ``next_step_id``  — advance to a successor StepNode (inter-step);
                            the engine enters it at its ``first_task_id``.
      - ``status``        — resolve the journey to a terminal state.

    If all three routing fields are None the Outcome is a **fallthrough
    signal**: the condition matched but no destination is set. The engine
    treats this identically to finding no matching Outcome at the current
    routing level and escalates accordingly.

    If ``condition`` is None the Outcome is **unconditional** and always
    matches (acts as a default / catch-all edge).

    Attributes:
        condition:    Optional callable ``(payload, context) -> bool``.
                      None means an unconditional (default) transition.
        next_task_id: Target TaskNode ID for intra-step routing.
                      Mutually exclusive with next_step_id and status.
        next_step_id: Target StepNode ID for inter-step routing.
                      Mutually exclusive with next_task_id and status.
        status:       Terminal journey status to assign when this Outcome
                      is taken. One of "accepted" or "rejected".
                      Mutually exclusive with next_task_id and next_step_id.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    condition: Callable[[Dict[str, Any], Dict[str, Any]], bool] | None = Field(
        default=None,
        description=(
            "Callable(payload, context) -> bool. "
            "None means this is an unconditional default transition."
        ),
    )
    next_task_id: str | None = Field(
        default=None,
        description=(
            "ID of the destination TaskNode for intra-step routing. "
            "Mutually exclusive with next_step_id and status."
        ),
    )
    next_step_id: str | None = Field(
        default=None,
        description=(
            "ID of the destination StepNode for inter-step routing. "
            "The engine enters the step at its first_task_id. "
            "Mutually exclusive with next_task_id and status."
        ),
    )
    status: Literal["accepted", "rejected"] | None = Field(
        default=None,
        description=(
            "Terminal journey status to assign when this Outcome is taken. "
            "Mutually exclusive with next_task_id and next_step_id."
        ),
    )

    @model_validator(mode="after")
    def check_exclusive_targets(self) -> "Outcome":
        """
        Enforce mutual exclusivity across the three routing fields.

        Raises:
            ValueError: If more than one of next_task_id, next_step_id,
                        or status is populated simultaneously.
        """
        populated: int = sum(
            field is not None
            for field in (self.next_task_id, self.next_step_id, self.status)
        )
        if populated > 1:
            raise ValueError(
                "Outcome can only have one target routing field defined. "
                f"Received next_task_id={self.next_task_id!r}, "
                f"next_step_id={self.next_step_id!r}, "
                f"status={self.status!r}."
            )
        return self


class BaseNode(BaseModel):
    """
    Abstract base for all graph nodes (TaskNode, StepNode).

    Centralises the fields and Pydantic configuration shared by every
    node type so that concrete subclasses remain focused on their own
    responsibilities.

    Attributes:
        id:   Unique identifier for this node within the graph.
        name: Human-readable label for display and logging purposes.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(description="Unique node identifier.")
    name: str = Field(description="Human-readable node label.")


class TaskNode(BaseNode):
    """
    Represents an atomic unit of work within a workflow step.

    A TaskNode owns a validator that gates entry (ensuring the
    incoming payload is well-formed) and a list of Outcome objects
    that the engine evaluates in order to route the user onward.

    Inherits `id` and `name` from BaseNode.

    Attributes:
        validator:  Optional callable that receives the raw payload dict
                    and returns True if the payload is acceptable.
                    Returning False causes the engine to reject the
                    submission before any Outcome is evaluated.
        next_tasks: Ordered, explicitly-typed conditional edges to subsequent
                    destinations. Each Outcome carries one of three mutually
                    exclusive routing fields (next_task_id, next_step_id, or
                    status). The engine evaluates them sequentially and acts
                    on the first Outcome whose condition matches. If the list
                    is empty, no condition matches, or the matched Outcome is
                    a fallthrough signal (all routing fields None), the engine
                    escalates to the parent StepNode's next_steps.
    """

    validator: Callable[[Dict[str, Any]], bool] | None = Field(
        default=None,
        description=(
            "Callable(payload) -> bool. "
            "Guards task entry; None means no validation is applied."
        ),
    )
    next_tasks: List[Outcome] = Field(
        default_factory=list,
        description=(
            "Ordered, explicitly-typed conditional edges. "
            "Evaluated sequentially; the first matching Outcome is acted on. "
            "If empty, no condition matches, or the matched Outcome is a "
            "fallthrough (all routing fields None), the engine escalates "
            "to the parent StepNode's next_steps."
        ),
    )
    example_payload: Dict[str, Any] | None = Field(
        default=None,
        description="Optional example payload used to dynamically generate Swagger UI documentation."
    )


class StepNode(BaseNode):
    """
    Represents a major phase (stage) in the admissions workflow.

    A StepNode groups a sequence of TaskNodes under a single phase
    label (e.g. "Interview"). The engine enters a step at
    `first_task_id` and follows TaskNode outcomes until the step
    concludes, then consults `next_steps` to advance to the next phase.

    Inherits `id` and `name` from BaseNode.

    Attributes:
        first_task_id: The `id` of the TaskNode that begins this step.
                       The engine always enters a StepNode here, whether
                       arriving for the first time or via a fallthrough
                       from the previous step's next_steps resolution.
        next_steps:    Ordered, explicitly-typed conditional edges evaluated
                       at the step level when a child TaskNode falls through
                       (empty next_tasks, no condition match, or a fallthrough
                       signal). Each Outcome uses type-segregated routing:
                       next_step_id advances to a successor StepNode (entered
                       at its first_task_id); next_task_id routes to a specific
                       task; status resolves the journey to a terminal state.
                       A matched Outcome with all routing fields set to None
                       at this level raises a NoMatchingOutcomeError.
    """

    first_task_id: str = Field(
        description=(
            "ID of the TaskNode that serves as this step's entry point. "
            "Used both on initial entry and when arriving via fallthrough "
            "from a preceding step's next_steps resolution."
        )
    )
    next_steps: List[Outcome] = Field(
        default_factory=list,
        description=(
            "Ordered, explicitly-typed conditional edges evaluated at the "
            "step level on task-level fallthrough. Each Outcome uses "
            "type-segregated routing fields (next_step_id, next_task_id, "
            "or status). A matched Outcome with all routing fields None "
            "at this level raises a NoMatchingOutcomeError."
        ),
    )


class UserState(BaseModel):
    """
    Tracks the mutable journey state for a single applicant.

    UserState is the runtime record that the engine reads and writes
    as a user progresses through the workflow graph. The `context`
    dict accumulates historical data (scores, decisions, timestamps)
    that Outcome conditions may inspect.

    Attributes:
        user_id:          Unique identifier for the applicant.
        current_step_id:  ID of the StepNode the user is currently in.
        current_task_id:  ID of the TaskNode the user must complete next.
        context:          Accumulated historical data keyed by arbitrary
                          strings (e.g. {"iq_score": 85}).
        status:           Lifecycle status of this user's journey.
                          One of: "in_progress", "accepted", "rejected".
    """

    user_id: str = Field(description="Unique applicant identifier.")
    current_step_id: str = Field(description="ID of the user's current StepNode.")
    current_task_id: str = Field(description="ID of the user's current TaskNode.")
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Accumulated historical data available to Outcome conditions.",
    )
    status: Literal["in_progress", "accepted", "rejected"] = Field(
        default="in_progress",
        description="Journey status: one of 'in_progress', 'accepted', or 'rejected'.",
    )


class TaskPayload(BaseModel):
    """
    Incoming webhook contract for a task submission.

    Submitted by an external system (e.g. an ATS or scheduling tool)
    when an applicant completes an action. The engine uses `user_id`
    to load UserState, `step_id` and `task_id` to validate the
    submission is for the expected position in the graph, and `payload`
    to run the TaskNode's validator and Outcome conditions.

    Attributes:
        user_id:  ID of the applicant this submission belongs to.
        step_id:  ID of the step being submitted.
        task_id:  ID of the task being submitted.
        payload:  Arbitrary key-value data produced by the external system.
    """

    user_id: str = Field(description="ID of the applicant.")
    step_id: str = Field(description="ID of the step being submitted.")
    task_id: str = Field(description="ID of the task being submitted.")
    payload: Dict[str, Any] = Field(
    description="Arbitrary key-value data."
    )