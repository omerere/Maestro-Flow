"""
Workflow engine for the Maestro-Flow admissions system.

Contains WorkflowEngine, the central class responsible for navigating
the conditional linked-node graph. It implements a two-level hierarchical
routing strategy:

  Level 1 (Task routing)     — evaluate the current TaskNode's next_tasks.
                               A matching outcome may advance to another task
                               or immediately resolve to a terminal status.
  Level 2 (Step fallthrough) — if Level 1 yields no match, evaluate the
                               current StepNode's next_steps and either
                               resolve to a terminal status or enter the
                               successor StepNode at its first_task_id.
"""

import logging
from typing import Any, Dict, List

from app.models.schemas import (
    Outcome,
    StepNode,
    TaskNode,
    TaskPayload,
    UserState,
)

logger = logging.getLogger(__name__)


class WorkflowEngineError(Exception):
    """Base exception for all WorkflowEngine failures."""


class NodeNotFoundError(WorkflowEngineError):
    """Raised when a node ID cannot be resolved in the engine's registry."""


class NoMatchingOutcomeError(WorkflowEngineError):
    """Raised when neither task-level nor step-level routing finds a match."""


class WorkflowEngine:
    """
    Navigates an applicant through the Maestro-Flow workflow graph.

    The engine is stateless with respect to individual users; all mutable
    journey data lives in UserState objects managed by the caller. The
    engine receives a snapshot, processes one webhook event, and returns
    the updated snapshot without mutating the original.

    Attributes:
        steps: Registry mapping step IDs to their StepNode definitions.
        tasks: Registry mapping task IDs to their TaskNode definitions.
    """

    def __init__(
        self,
        steps: Dict[str, StepNode],
        tasks: Dict[str, TaskNode],
    ) -> None:
        """
        Initialise the engine with the static workflow graph.

        Args:
            steps: A dict mapping each StepNode's `id` to its StepNode.
            tasks: A dict mapping each TaskNode's `id` to its TaskNode.
        """
        self.steps: Dict[str, StepNode] = steps
        self.tasks: Dict[str, TaskNode] = tasks
        logger.info(
            "WorkflowEngine initialised with %d step(s) and %d task(s).",
            len(self.steps),
            len(self.tasks),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process_webhook(
        self,
        payload: TaskPayload,
        user: UserState,
    ) -> UserState:
        """
        Process a single webhook submission and advance the user's journey.

        Executes the following pipeline:
          1. Resolve and validate the submission against the current TaskNode.
          2. Merge the submission payload into the user's accumulated context.
          3. Level 1 — task-level routing via next_tasks Outcomes.
             A match may advance to another TaskNode or resolve a terminal
             status ("accepted" / "rejected") immediately.
          4. Level 2 — step-level fallthrough via next_steps Outcomes when
             Level 1 produces no match. A match may resolve a terminal
             status or transition to a successor StepNode.

        Args:
            payload: The incoming webhook data, including task identification
                     and the raw submission payload dict.
            user:    The applicant's current journey state. Not mutated;
                     an updated copy is returned.

        Returns:
            An updated UserState reflecting the new position in the graph
            or a terminal status ("accepted" / "rejected").

        Raises:
            NodeNotFoundError:      If a referenced task or step ID is absent
                                    from the engine's registry.
            ValueError:             If the journey is no longer in progress, if 
                                    the webhook targets the wrong task, or if 
                                    the TaskNode's validator rejects the payload.
            NoMatchingOutcomeError: If routing fails at both levels.
        """
        logger.info(
            "Processing webhook for user '%s' | step='%s' task='%s'.",
            user.user_id,
            payload.step_id,
            payload.task_id,
        )

        # -- 0. Guard: reject submissions from users in a terminal state --
        if user.status != "in_progress":
            raise ValueError(
                f"User '{user.user_id}' has a terminal status "
                f"'{user.status}' and cannot accept further submissions."
            )

        # -- 1. Resolve and validate the current task node ----------------
        current_task: TaskNode = self._get_task(user.current_task_id)
        self._assert_task_match(payload, current_task)
        self._run_validator(payload.payload, current_task)

        # -- 2. Merge submission data into the user's context -------------
        user = self._merge_context(user, payload.payload, current_task.id)

        # -- 3. Level 1 routing: attempt task-level transition ------------
        routed_user: UserState | None = self._route_task_level(
            user=user,
            current_task=current_task,
            payload=payload.payload,
        )
        if routed_user is not None:
            return routed_user

        # -- 4. Level 2 routing: step-level fallthrough -------------------
        return self._route_step_level(user=user, payload=payload.payload)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_task(self, task_id: str) -> TaskNode:
        """
        Retrieve a TaskNode by ID from the registry.

        Args:
            task_id: The ID to look up in the tasks registry.

        Returns:
            The corresponding TaskNode.

        Raises:
            NodeNotFoundError: If task_id is not present in self.tasks.
        """
        task: TaskNode | None = self.tasks.get(task_id)
        if task is None:
            raise NodeNotFoundError(
                f"TaskNode '{task_id}' not found in the engine registry. "
                f"Available tasks: {list(self.tasks.keys())}."
            )
        return task

    def _get_step(self, step_id: str) -> StepNode:
        """
        Retrieve a StepNode by ID from the registry.

        Args:
            step_id: The ID to look up in the steps registry.

        Returns:
            The corresponding StepNode.

        Raises:
            NodeNotFoundError: If step_id is not present in self.steps.
        """
        step: StepNode | None = self.steps.get(step_id)
        if step is None:
            raise NodeNotFoundError(
                f"StepNode '{step_id}' not found in the engine registry. "
                f"Available steps: {list(self.steps.keys())}."
            )
        return step

    def _assert_task_match(
        self,
        payload: TaskPayload,
        current_task: TaskNode,
    ) -> None:
        """
        Verify the webhook's task_id matches the user's current task.

        Guards against out-of-order or mis-routed webhook submissions.
        """
        if payload.task_id != current_task.id:
            raise ValueError(
                f"Webhook targets task '{payload.task_id}' but user is "
                f"currently on task '{current_task.id}'. Submission rejected."
            )

    def _run_validator(
        self,
        raw_payload: Dict[str, Any],
        current_task: TaskNode,
    ) -> None:
        """
        Execute the TaskNode's validator against the raw submission payload.

        A return value of False is treated as a validation failure. If no
        validator is configured the call is a no-op.

        Args:
            raw_payload:  The `payload` dict from the incoming TaskPayload.
            current_task: The TaskNode whose validator is to be executed.

        Raises:
            ValueError: If the validator callable returns False, or if it
                        raises an unexpected exception internally.
        """
        if current_task.validator is None:
            return

        try:
            is_valid: bool = current_task.validator(raw_payload)
        except Exception as exc:
            raise ValueError(
                f"Validator for task '{current_task.id}' raised an unexpected "
                f"exception: {exc}"
            ) from exc

        if not is_valid:
            raise ValueError(
                f"Payload failed validation for task '{current_task.id}' "
                f"('{current_task.name}'). Submission rejected."
            )

    def _merge_context(
        self,
        user: UserState,
        raw_payload: Dict[str, Any],
        task_id: str,
    ) -> UserState:
        """
        Merge submission data into the user's accumulated context.

        Returns an updated copy of UserState; the original is not mutated.
        Existing context keys are preserved; submission keys overwrite on
        collision, allowing callers to correct prior submissions.

        Args:
            user:        The current UserState.
            raw_payload: The ``payload`` dict from the incoming TaskPayload.
            task_id:     The ID of the current TaskNode; used to build the
                         attempt counter key ``f"{task_id}_attempts"``.
                         Incremented once per call so that Outcome conditions
                         see the updated count immediately.

        Returns:
            A new UserState with an updated context dict.
        """
        merged: Dict[str, Any] = {**user.context, **raw_payload}
        attempt_key = f"{task_id}_attempts"
        merged[attempt_key] = merged.get(attempt_key, 0) + 1
        return user.model_copy(update={"context": merged})

    def _route_task_level(
        self,
        user: UserState,
        current_task: TaskNode,
        payload: Dict[str, Any],
    ) -> UserState | None:
        """
        Attempt Level 1 (task-level) routing for an applicant.

        Evaluates the current TaskNode's next_tasks Outcomes in order and
        returns an updated UserState if a matching Outcome has a concrete
        routing target (status, next_task_id, or next_step_id).

        Returns None in two cases, both of which signal the caller to
        escalate to Level 2 step routing:
          - No Outcome condition matched (or the list is empty).
          - An Outcome condition matched but all routing fields are None
            (explicit fallthrough signal).

        Args:
            user:         The applicant's current (context-merged) state.
            current_task: The TaskNode the user is currently positioned on.
            payload:      The raw submission payload dict.

        Returns:
            An updated UserState, or None to signal a fallthrough to Level 2.
        """
        task_outcome: Outcome | None = self._evaluate_outcomes(
            outcomes=current_task.next_tasks,
            payload=payload,
            context=user.context,
        )

        if task_outcome is None:
            logger.info(
                "No Level 1 Outcome matched for user '%s'; falling through.",
                user.user_id,
            )
            return None

        if task_outcome.status:
            # (a) Terminal status resolved directly from a task-level outcome.
            logger.info(
                "User '%s' reached terminal status '%s' via task-level routing.",
                user.user_id,
                task_outcome.status,
            )
            return user.model_copy(update={"status": task_outcome.status})

        elif task_outcome.next_task_id:
            # (b) Advance to another TaskNode within the same step.
            logger.info(
                "Level 1 match for user '%s': routing to task '%s'.",
                user.user_id,
                task_outcome.next_task_id,
            )
            # Verify the target task exists before committing the state change.
            self._get_task(task_outcome.next_task_id)
            return user.model_copy(
                update={"current_task_id": task_outcome.next_task_id}
            )

        elif task_outcome.next_step_id:
            # (c) Jump directly to a StepNode from a task-level outcome.
            next_step: StepNode = self._get_step(task_outcome.next_step_id)
            # Verify the entry task exists before committing the state change.
            self._get_task(next_step.first_task_id)
            logger.info(
                "Level 1 match for user '%s': routing directly to step '%s', "
                "entering at task '%s'.",
                user.user_id,
                next_step.id,
                next_step.first_task_id,
            )
            return user.model_copy(
                update={
                    "current_step_id": next_step.id,
                    "current_task_id": next_step.first_task_id,
                }
            )

        else:
            # (d) All routing fields are None — explicit fallthrough signal.
            # Signal the caller to escalate to Level 2.
            logger.info(
                "Level 1 outcome for user '%s' is a fallthrough signal "
                "(all routing fields None); escalating to step routing.",
                user.user_id,
            )
            return None

    def _route_step_level(
        self,
        user: UserState,
        payload: Dict[str, Any],
    ) -> UserState:
        """
        Execute Level 2 (step-level) fallthrough routing for an applicant.

        Fetches the current StepNode and evaluates its next_steps Outcomes.
        Returns an updated UserState if a matching Outcome resolves to a
        concrete routing target. Raises NoMatchingOutcomeError if no Outcome
        matches or if the matched Outcome is a fallthrough signal (all routing
        fields None), as there is no further level to escalate to.

        Args:
            user:    The applicant's current (context-merged) state.
            payload: The raw submission payload dict.

        Returns:
            An updated UserState.

        Raises:
            NoMatchingOutcomeError: If routing cannot be resolved at this level.
        """
        logger.info(
            "No Level 1 match for user '%s'; falling through to step routing.",
            user.user_id,
        )
        current_step: StepNode = self._get_step(user.current_step_id)
        step_outcome: Outcome | None = self._evaluate_outcomes(
            outcomes=current_step.next_steps,
            payload=payload,
            context=user.context,
        )

        if step_outcome is None:
            raise NoMatchingOutcomeError(
                f"No matching Outcome found at task or step level for user "
                f"'{user.user_id}' (step='{user.current_step_id}', "
                f"task='{user.current_task_id}'). "
                f"Ensure the workflow graph has a default (condition=None) "
                f"Outcome or verify the applicant's context data."
            )

        if step_outcome.status:
            # (a) Terminal status resolved from a step-level outcome.
            logger.info(
                "User '%s' reached terminal status '%s' via step-level routing.",
                user.user_id,
                step_outcome.status,
            )
            return user.model_copy(update={"status": step_outcome.status})

        elif step_outcome.next_task_id:
            # (b) Step-level outcome routes to a specific TaskNode.
            logger.info(
                "Level 2 match for user '%s': routing to task '%s'.",
                user.user_id,
                step_outcome.next_task_id,
            )
            # Verify the target task exists before committing the state change.
            self._get_task(step_outcome.next_task_id)
            return user.model_copy(
                update={"current_task_id": step_outcome.next_task_id}
            )

        elif step_outcome.next_step_id:
            # (c) Advance to a successor StepNode, entering at its first_task_id.
            next_step: StepNode = self._get_step(step_outcome.next_step_id)
            # Verify the entry task exists before committing the state change.
            self._get_task(next_step.first_task_id)
            logger.info(
                "Level 2 match for user '%s': routing to step '%s', "
                "entering at task '%s'.",
                user.user_id,
                next_step.id,
                next_step.first_task_id,
            )
            return user.model_copy(
                update={
                    "current_step_id": next_step.id,
                    "current_task_id": next_step.first_task_id,
                }
            )

        else:
            # (d) Matched step-level outcome has all routing fields set to None.
            # There is nowhere left to fall through; this is a workflow
            # configuration error.
            raise NoMatchingOutcomeError(
                f"Step-level Outcome for user '{user.user_id}' matched a "
                f"condition but has no routing target set "
                f"(step='{user.current_step_id}'). "
                f"This is a workflow graph configuration error."
            )

    def _evaluate_outcomes(
        self,
        outcomes: List[Outcome],
        payload: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Outcome | None:
        """
        Evaluate an ordered list of Outcomes and return the first match.

        An Outcome matches when its condition callable returns True, or when
        condition is None (unconditional / default transition). Outcomes are
        evaluated in list order; only the first match is returned.

        A condition callable that raises an exception is logged as a warning
        and skipped so that subsequent outcomes are still evaluated.

        Args:
            outcomes: The ordered list of Outcome edges to evaluate.
            payload:  The raw submission payload dict passed to conditions.
            context:  The user's accumulated context dict passed to conditions.

        Returns:
            The first matching Outcome, or None if no Outcome matches.
        """
        for outcome in outcomes:
            if outcome.condition is None:
                # Unconditional edge — always matches; acts as a default.
                return outcome

            try:
                if outcome.condition(payload, context):
                    return outcome
            except Exception as exc:
                # A misbehaving condition must not silently swallow the error
                # or short-circuit evaluation of remaining outcomes.
                logger.warning(
                    "Condition callable for outcome (next_task_id=%r, "
                    "next_step_id=%r, status=%r) raised an exception "
                    "and will be skipped: %s",
                    outcome.next_task_id,
                    outcome.next_step_id,
                    outcome.status,
                    exc,
                )

        return None
