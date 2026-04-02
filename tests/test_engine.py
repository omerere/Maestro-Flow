"""
Unit tests for WorkflowEngine in app.core.engine.

Uses a minimal, self-contained workflow graph to test engine mechanics in
isolation, without coupling to the full Maestro-Flow admissions configuration.

Two-level routing under test:
  Level 1 (task) — evaluate TaskNode.next_tasks Outcomes.
  Level 2 (step) — fallthrough to StepNode.next_steps when Level 1 yields
                   nothing (empty list, no condition match, or explicit
                   fallthrough signal where all routing fields are None).

Graph layout used in this module
─────────────────────────────────
Tasks
  task_empty        — no validator, no outcomes  → always falls through
  task_chain_a      — routes to task_chain_b (Level 1 task-to-task)
  task_chain_b      — no outcomes → falls through
  task_step_jump    — routes directly to step_b (Level 1 task-to-step)
  task_to_accept    — resolves status="accepted" at Level 1
  task_to_reject    — resolves status="rejected" at Level 1
  task_fallthrough  — condition always matches but all routing fields None
                      → explicit fallthrough signal, escalates to Level 2
  task_validated    — validator requires "required_key" in payload
  task_cond_except  — first condition raises; second is unconditional/accepted

Steps
  step_a            — task_empty → next_steps routes to step_b
  step_b            — task_empty → next_steps resolves "accepted"
  step_chain        — task_chain_a (→ task_chain_b) → next_steps "accepted"
  step_task_accept  — task_to_accept resolves immediately at Level 1
  step_task_reject  — task_to_reject resolves immediately at Level 1
  step_empty        — task_empty, no next_steps → NoMatchingOutcomeError
  step_fallthrough  — task_fallthrough (explicit ft) → next_steps "accepted"
  step_validated    — task_validated → next_steps "accepted"
  step_cond_except  — task_cond_except → no next_steps needed (resolved L1)
  step_task_step_j  — task_step_jump routes Level 1 directly to step_b
"""

import pytest

from app.core.engine import (
    NoMatchingOutcomeError,
    NodeNotFoundError,
    WorkflowEngine,
)
from app.models.schemas import Outcome, StepNode, TaskNode, TaskPayload, UserState


# ---------------------------------------------------------------------------
# Module-level condition helpers (named functions for readable tracebacks)
# ---------------------------------------------------------------------------


def _always_true(payload, context):
    """Condition that unconditionally returns True."""
    return True


def _always_false(payload, context):
    """Condition that unconditionally returns False."""
    return False


def _condition_raises(payload, context):
    """Condition that always raises, simulating a misbehaving callable."""
    raise RuntimeError("Simulated condition failure.")


# ---------------------------------------------------------------------------
# Fixtures: minimal graph
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_tasks():
    return {
        "task_empty": TaskNode(
            id="task_empty",
            name="Task Empty",
            validator=None,
            next_tasks=[],
        ),
        # Level 1 task-to-task: chain_a always advances to chain_b.
        "task_chain_a": TaskNode(
            id="task_chain_a",
            name="Task Chain A",
            validator=None,
            next_tasks=[Outcome(condition=None, next_task_id="task_chain_b")],
        ),
        "task_chain_b": TaskNode(
            id="task_chain_b",
            name="Task Chain B",
            validator=None,
            next_tasks=[],
        ),
        # Level 1 task-to-step: jumps directly to step_b, bypassing step-level
        # routing of the originating step.
        "task_step_jump": TaskNode(
            id="task_step_jump",
            name="Task Step Jump",
            validator=None,
            next_tasks=[Outcome(condition=None, next_step_id="step_b")],
        ),
        # Terminal outcomes at Level 1.
        "task_to_accept": TaskNode(
            id="task_to_accept",
            name="Task To Accept",
            validator=None,
            next_tasks=[Outcome(condition=None, status="accepted")],
        ),
        "task_to_reject": TaskNode(
            id="task_to_reject",
            name="Task To Reject",
            validator=None,
            next_tasks=[Outcome(condition=None, status="rejected")],
        ),
        # Explicit fallthrough signal: condition matches but all routing fields
        # are None → engine returns None from _route_task_level → Level 2 used.
        "task_fallthrough": TaskNode(
            id="task_fallthrough",
            name="Task Fallthrough",
            validator=None,
            next_tasks=[Outcome(condition=_always_true)],
        ),
        # Validator-gated: requires "required_key" in the payload.
        "task_validated": TaskNode(
            id="task_validated",
            name="Task Validated",
            validator=lambda p: "required_key" in p,
            next_tasks=[],
        ),
        # First condition raises (skipped); second is unconditional → accepted.
        "task_cond_except": TaskNode(
            id="task_cond_except",
            name="Task Cond Except",
            validator=None,
            next_tasks=[
                Outcome(condition=_condition_raises),
                Outcome(condition=None, status="accepted"),
            ],
        ),
    }


@pytest.fixture
def minimal_steps():
    return {
        # Falls through at task level → Level 2 routes to step_b.
        "step_a": StepNode(
            id="step_a",
            name="Step A",
            first_task_id="task_empty",
            next_steps=[Outcome(condition=None, next_step_id="step_b")],
        ),
        # Resolves "accepted" at Level 2.
        "step_b": StepNode(
            id="step_b",
            name="Step B",
            first_task_id="task_empty",
            next_steps=[Outcome(condition=None, status="accepted")],
        ),
        # task_chain_a → task_chain_b → fallthrough → Level 2 → "accepted".
        "step_chain": StepNode(
            id="step_chain",
            name="Step Chain",
            first_task_id="task_chain_a",
            next_steps=[Outcome(condition=None, status="accepted")],
        ),
        # Immediate Level 1 resolution; next_steps never reached.
        "step_task_accept": StepNode(
            id="step_task_accept",
            name="Step Task Accept",
            first_task_id="task_to_accept",
            next_steps=[],
        ),
        "step_task_reject": StepNode(
            id="step_task_reject",
            name="Step Task Reject",
            first_task_id="task_to_reject",
            next_steps=[],
        ),
        # No next_steps → NoMatchingOutcomeError on Level 2 fallthrough.
        "step_empty": StepNode(
            id="step_empty",
            name="Step Empty",
            first_task_id="task_empty",
            next_steps=[],
        ),
        # Explicit fallthrough task → Level 2 resolves "accepted".
        "step_fallthrough": StepNode(
            id="step_fallthrough",
            name="Step Fallthrough",
            first_task_id="task_fallthrough",
            next_steps=[Outcome(condition=None, status="accepted")],
        ),
        # Validator-gated task → Level 2 resolves "accepted" when task passes.
        "step_validated": StepNode(
            id="step_validated",
            name="Step Validated",
            first_task_id="task_validated",
            next_steps=[Outcome(condition=None, status="accepted")],
        ),
        # task_cond_except resolves at Level 1 (bad condition skipped,
        # unconditional fires); no Level 2 needed.
        "step_cond_except": StepNode(
            id="step_cond_except",
            name="Step Cond Except",
            first_task_id="task_cond_except",
            next_steps=[],
        ),
        # Originating step for the task-to-step jump test.
        "step_task_step_jump": StepNode(
            id="step_task_step_jump",
            name="Step Task Step Jump",
            first_task_id="task_step_jump",
            next_steps=[],
        ),
    }


@pytest.fixture
def engine(minimal_tasks, minimal_steps):
    return WorkflowEngine(steps=minimal_steps, tasks=minimal_tasks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(step_id: str, task_id: str, context: dict | None = None) -> UserState:
    """Build a minimal UserState positioned at the given step and task."""
    return UserState(
        user_id="test_user",
        current_step_id=step_id,
        current_task_id=task_id,
        context=context or {},
    )


def _payload(task_id: str, data: dict | None = None) -> TaskPayload:
    """Build a TaskPayload whose task_id matches the given task ID."""
    return TaskPayload(
        user_id="test_user",
        step_id="irrelevant",
        task_id=task_id,  # engine accepts both id and name
        payload=data or {},
    )


# ---------------------------------------------------------------------------
# Tests: Level 2 — step-level fallthrough routing
# ---------------------------------------------------------------------------


class TestStepLevelRouting:
    """Engine escalates to the current StepNode's next_steps when Level 1
    produces no match (empty next_tasks list or no condition hit)."""

    def test_empty_task_advances_to_next_step(self, engine):
        user = _user("step_a", "task_empty")
        result = engine.process_webhook(_payload("task_empty"), user)

        assert result.current_step_id == "step_b"
        assert result.current_task_id == "task_empty"  # step_b.first_task_id
        assert result.status == "in_progress"

    def test_two_step_journey_resolves_accepted(self, engine):
        # step_a → step_b (Level 2) → step_b resolves "accepted" (Level 2).
        user = _user("step_a", "task_empty")
        user = engine.process_webhook(_payload("task_empty"), user)
        assert user.current_step_id == "step_b"

        result = engine.process_webhook(_payload("task_empty"), user)
        assert result.status == "accepted"

    def test_step_level_resolves_terminal_status(self, engine):
        # step_b.next_steps has Outcome(status="accepted").
        user = _user("step_b", "task_empty")
        result = engine.process_webhook(_payload("task_empty"), user)
        assert result.status == "accepted"


# ---------------------------------------------------------------------------
# Tests: Level 1 — task-level routing
# ---------------------------------------------------------------------------


class TestTaskLevelRouting:
    """Engine acts on a matching Level 1 Outcome before reaching Level 2."""

    def test_routes_to_next_task_within_step(self, engine):
        # task_chain_a → task_chain_b (same step, same step_id preserved).
        user = _user("step_chain", "task_chain_a")
        result = engine.process_webhook(_payload("task_chain_a"), user)

        assert result.current_task_id == "task_chain_b"
        assert result.current_step_id == "step_chain"
        assert result.status == "in_progress"

    def test_chained_task_then_falls_through_to_step(self, engine):
        # task_chain_a → task_chain_b; task_chain_b → Level 2 → accepted.
        user = _user("step_chain", "task_chain_a")
        user = engine.process_webhook(_payload("task_chain_a"), user)
        assert user.current_task_id == "task_chain_b"

        result = engine.process_webhook(_payload("task_chain_b"), user)
        assert result.status == "accepted"

    def test_routes_directly_to_step_from_task_level(self, engine):
        # task_step_jump routes to step_b at Level 1, bypassing step-level
        # routing of the originating step.
        user = _user("step_task_step_jump", "task_step_jump")
        result = engine.process_webhook(_payload("task_step_jump"), user)

        assert result.current_step_id == "step_b"
        assert result.current_task_id == "task_empty"  # step_b.first_task_id
        assert result.status == "in_progress"

    def test_task_level_resolves_accepted(self, engine):
        user = _user("step_task_accept", "task_to_accept")
        result = engine.process_webhook(_payload("task_to_accept"), user)
        assert result.status == "accepted"

    def test_task_level_resolves_rejected(self, engine):
        user = _user("step_task_reject", "task_to_reject")
        result = engine.process_webhook(_payload("task_to_reject"), user)
        assert result.status == "rejected"


# ---------------------------------------------------------------------------
# Tests: Explicit fallthrough signal
# ---------------------------------------------------------------------------


class TestExplicitFallthrough:
    """An Outcome whose condition matches but has all routing fields None is
    an explicit fallthrough signal; the engine escalates to Level 2."""

    def test_matching_all_none_outcome_escalates_to_step(self, engine):
        # task_fallthrough: _always_true condition, all fields None.
        # step_fallthrough.next_steps resolves "accepted".
        user = _user("step_fallthrough", "task_fallthrough")
        result = engine.process_webhook(_payload("task_fallthrough"), user)
        assert result.status == "accepted"

    def test_explicit_fallthrough_does_not_block_step_routing(self, engine):
        # The engine must not treat the all-None Outcome as a terminal state;
        # step-level routing must still fire and can resolve differently.
        user = _user("step_fallthrough", "task_fallthrough")
        result = engine.process_webhook(_payload("task_fallthrough"), user)
        # If fallthrough were incorrectly suppressed the result would be
        # "in_progress" or raise; "accepted" confirms Level 2 was used.
        assert result.status != "in_progress"


# ---------------------------------------------------------------------------
# Tests: NoMatchingOutcomeError
# ---------------------------------------------------------------------------


class TestNoMatchingOutcomeError:
    def test_raises_when_both_levels_have_no_outcomes(self, engine):
        # step_empty: task_empty (no outcomes) + no next_steps.
        user = _user("step_empty", "task_empty")
        with pytest.raises(NoMatchingOutcomeError):
            engine.process_webhook(_payload("task_empty"), user)

    def test_error_message_includes_user_and_position(self, engine):
        user = _user("step_empty", "task_empty")
        with pytest.raises(NoMatchingOutcomeError, match="test_user"):
            engine.process_webhook(_payload("task_empty"), user)


# ---------------------------------------------------------------------------
# Tests: NodeNotFoundError
# ---------------------------------------------------------------------------


class TestNodeNotFoundError:
    def test_raises_for_unknown_current_task_id(self, engine):
        user = _user("step_a", "nonexistent_task")
        with pytest.raises(NodeNotFoundError):
            engine.process_webhook(
                TaskPayload(
                    user_id="test_user",
                    step_id="step_a",
                    task_id="nonexistent_task",
                    payload={},
                ),
                user,
            )

    def test_raises_for_unknown_current_step_id_on_fallthrough(self, engine):
        # task_empty has no outcomes; the engine then looks up current_step_id.
        user = _user("nonexistent_step", "task_empty")
        with pytest.raises(NodeNotFoundError):
            engine.process_webhook(_payload("task_empty"), user)

    def test_error_message_includes_missing_id(self, engine):
        user = _user("step_a", "ghost_task")
        with pytest.raises(NodeNotFoundError, match="ghost_task"):
            engine.process_webhook(
                TaskPayload(
                    user_id="test_user",
                    step_id="step_a",
                    task_id="ghost_task",
                    payload={},
                ),
                user,
            )


# ---------------------------------------------------------------------------
# Tests: Validator gating
# ---------------------------------------------------------------------------


class TestValidatorGating:
    def test_valid_payload_allows_progression(self, engine):
        user = _user("step_validated", "task_validated")
        result = engine.process_webhook(
            _payload("task_validated", {"required_key": "any_value"}),
            user,
        )
        assert result.status == "accepted"

    def test_missing_required_key_raises_value_error(self, engine):
        user = _user("step_validated", "task_validated")
        with pytest.raises(ValueError, match="Payload failed validation"):
            engine.process_webhook(_payload("task_validated", {"wrong": "data"}), user)

    def test_empty_payload_raises_value_error(self, engine):
        user = _user("step_validated", "task_validated")
        with pytest.raises(ValueError, match="Payload failed validation"):
            engine.process_webhook(_payload("task_validated", {}), user)

    def test_none_validator_accepts_any_payload(self, engine):
        # task_empty has validator=None; any payload (including {}) is accepted.
        user = _user("step_b", "task_empty")
        result = engine.process_webhook(_payload("task_empty", {}), user)
        assert result.status == "accepted"


# ---------------------------------------------------------------------------
# Tests: Task name matching 
# ---------------------------------------------------------------------------

class TestTaskIDMatching:
    """The engine strictly requires the webhook's task_id to match the TaskNode's ID."""

    def test_task_matched_by_id(self, engine):
        user = _user("step_b", "task_empty")
        result = engine.process_webhook(
            TaskPayload(
                user_id="test_user",
                step_id="step_b",
                task_id="task_empty",
                payload={},
            ),
            user,
        )
        assert result is not None

    def test_wrong_task_id_raises_value_error(self, engine):
        user = _user("step_a", "task_empty")
        with pytest.raises(ValueError, match="Webhook targets task"):
            engine.process_webhook(
                TaskPayload(
                    user_id="test_user",
                    step_id="step_a",
                    task_id="completely_wrong_task",
                    payload={},
                ),
                user,
            )

    def test_error_message_includes_wrong_and_current_task_ids(self, engine):
        user = _user("step_a", "task_empty")
        with pytest.raises(ValueError, match="completely_wrong"):
            engine.process_webhook(
                TaskPayload(
                    user_id="test_user",
                    step_id="step_a",
                    task_id="completely_wrong",
                    payload={},
                ),
                user,
            )


# ---------------------------------------------------------------------------
# Tests: Context merging
# ---------------------------------------------------------------------------


class TestContextMerging:
    def test_payload_data_is_merged_into_user_context(self, engine):
        user = _user("step_b", "task_empty")
        result = engine.process_webhook(
            TaskPayload(
                user_id="test_user",
                step_id="step_b",
                task_id="task_empty",
                payload={"foo": "bar", "num": 42},
            ),
            user,
        )
        assert result.context["foo"] == "bar"
        assert result.context["num"] == 42

    def test_existing_context_keys_are_preserved(self, engine):
        user = _user("step_b", "task_empty", context={"prior": "value"})
        result = engine.process_webhook(
            TaskPayload(
                user_id="test_user",
                step_id="step_b",
                task_id="task_empty",
                payload={"new": "data"},
            ),
            user,
        )
        assert result.context["prior"] == "value"
        assert result.context["new"] == "data"

    def test_payload_key_overwrites_existing_context_key(self, engine):
        user = _user("step_b", "task_empty", context={"score": 50})
        result = engine.process_webhook(
            TaskPayload(
                user_id="test_user",
                step_id="step_b",
                task_id="task_empty",
                payload={"score": 90},
            ),
            user,
        )
        assert result.context["score"] == 90

    def test_original_user_state_is_not_mutated(self, engine):
        user = _user("step_b", "task_empty")
        engine.process_webhook(
            _payload("task_empty", {"sensitive": "data"}),
            user,
        )
        # The original UserState must be immutable.
        assert "sensitive" not in user.context

    def test_original_status_is_not_mutated(self, engine):
        user = _user("step_b", "task_empty")
        engine.process_webhook(_payload("task_empty"), user)
        assert user.status == "in_progress"


# ---------------------------------------------------------------------------
# Tests: Condition exception handling
# ---------------------------------------------------------------------------


class TestConditionExceptionHandling:
    """A condition callable that raises must be skipped; evaluation continues
    with the remaining outcomes in the list."""

    def test_raising_condition_is_skipped_and_next_outcome_fires(self, engine):
        # task_cond_except: condition raises → skipped → unconditional fires.
        user = _user("step_cond_except", "task_cond_except")
        result = engine.process_webhook(_payload("task_cond_except"), user)
        assert result.status == "accepted"

    def test_engine_does_not_propagate_condition_exception(self, engine):
        user = _user("step_cond_except", "task_cond_except")
        # RuntimeError from the condition must NOT bubble up.
        try:
            engine.process_webhook(_payload("task_cond_except"), user)
        except RuntimeError:
            pytest.fail(
                "WorkflowEngine propagated a RuntimeError from a condition callable."
            )


# ---------------------------------------------------------------------------
# Tests: Terminal-state guard
# ---------------------------------------------------------------------------


class TestTerminalStateGuard:
    """process_webhook must refuse further submissions from users whose
    journey has already resolved to a terminal status."""

    def test_rejected_user_raises_value_error(self, engine):
        user = _user("step_b", "task_empty")
        # Manufacture a rejected user directly.
        rejected = user.model_copy(update={"status": "rejected"})
        with pytest.raises(ValueError, match="terminal status"):
            engine.process_webhook(_payload("task_empty"), rejected)

    def test_accepted_user_raises_value_error(self, engine):
        user = _user("step_b", "task_empty")
        accepted = user.model_copy(update={"status": "accepted"})
        with pytest.raises(ValueError, match="terminal status"):
            engine.process_webhook(_payload("task_empty"), accepted)

    def test_in_progress_user_is_not_blocked(self, engine):
        # Sanity-check: a normal in_progress user must pass the guard.
        user = _user("step_b", "task_empty")
        result = engine.process_webhook(_payload("task_empty"), user)
        assert result.status == "accepted"

    def test_error_message_contains_user_id(self, engine):
        user = UserState(
            user_id="blocked_user_42",
            current_step_id="step_b",
            current_task_id="task_empty",
            status="rejected",
        )
        with pytest.raises(ValueError, match="blocked_user_42"):
            engine.process_webhook(_payload("task_empty"), user)

    def test_original_user_is_not_mutated_on_guard_failure(self, engine):
        user = _user("step_b", "task_empty")
        rejected = user.model_copy(update={"status": "rejected"})
        try:
            engine.process_webhook(_payload("task_empty"), rejected)
        except ValueError:
            pass
        # The rejected snapshot must still be rejected (immutability).
        assert rejected.status == "rejected"
