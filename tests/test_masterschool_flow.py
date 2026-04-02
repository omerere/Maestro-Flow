"""
Integration tests.

Instantiates WorkflowEngine with the real FLOW_STEPS and FLOW_TASKS from
app.core.flow_config and drives applicants through end-to-end journeys.
Unlike the unit tests in test_engine.py (which use a minimal synthetic
graph), these tests exercise the actual business-logic graph and verify
that the complete routing contract holds.

Paths covered
─────────────
  Happy Path    personal details → IQ pass (score > 75) → schedule →
                interview pass → upload ID → sign contract → payment →
                Slack → status "accepted"

  IQ Rejection  personal details → IQ fail (score ≤ 75) → "rejected"

  Interview     personal details → IQ pass → schedule →
  Rejection     interview fail (wrong decision) → "rejected"

  Validator     boundary tests confirming that missing payload keys are
  Enforcement   rejected before any routing is attempted
"""

import pytest

from app.core.engine import WorkflowEngine
from app.core.flow_config import (
    FLOW_STEPS,
    FLOW_TASKS,
    STARTING_STEP_ID,
    STARTING_TASK_ID,
)
from app.models.schemas import TaskPayload, UserState


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """WorkflowEngine initialised with the real admissions graph."""
    return WorkflowEngine(steps=FLOW_STEPS, tasks=FLOW_TASKS)


def _initial_user() -> UserState:
    """Return a fresh applicant positioned at the start of the workflow."""
    return UserState(
        user_id="applicant_001",
        current_step_id=STARTING_STEP_ID,
        current_task_id=STARTING_TASK_ID,
        context={},
    )


def _submit(engine: WorkflowEngine, user: UserState, task_id: str, data: dict) -> UserState:
    """Submit a webhook for the given task and return the updated UserState."""
    return engine.process_webhook(
        TaskPayload(
            user_id=user.user_id,
            step_id=user.current_step_id,
            task_id=task_id,
            payload=data,
        ),
        user,
    )


def _advance_to_iq(engine: WorkflowEngine) -> UserState:
    """Return a UserState positioned on perform_iq_test."""
    user = _initial_user()
    return _submit(
        engine,
        user,
        "submit_personal_details",
        {"first_name": "Alice", "last_name": "Smith", "email": "alice@example.com"},
    )


def _advance_to_interview(engine: WorkflowEngine) -> UserState:
    """Return a UserState positioned on perform_interview."""
    user = _advance_to_iq(engine)
    user = _submit(engine, user, "perform_iq_test", {"score": 85})
    return _submit(engine, user, "schedule_interview", {"interview_date": "2026-05-10"})


def _advance_to_sign_contract_step(engine: WorkflowEngine) -> UserState:
    """Return a UserState positioned at the start of sign_contract_step (upload_id)."""
    user = _advance_to_interview(engine)
    return _submit(engine, user, "perform_interview", {"decision": "passed_interview"})


def _advance_to_join_slack(engine: WorkflowEngine) -> UserState:
    """Return a UserState positioned on join_slack."""
    user = _advance_to_sign_contract_step(engine)
    user = _submit(engine, user, "upload_id", {"passport_number": "AB987654"})
    user = _submit(engine, user, "sign_contract", {})
    return _submit(engine, user, "submit_payment", {"payment_id": "pay_xyz_999"})


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """All steps completed successfully → status "accepted"."""

    def test_step_1_personal_details_advances_to_iq_step(self, engine):
        user = _initial_user()
        result = _submit(
            engine,
            user,
            "submit_personal_details",
            {"first_name": "Bob", "last_name": "Jones", "email": "bob@test.com"},
        )
        assert result.current_step_id == "iq_step"
        assert result.current_task_id == "perform_iq_test"
        assert result.status == "in_progress"

    def test_step_2_iq_pass_advances_to_interview_step(self, engine):
        user = _advance_to_iq(engine)
        result = _submit(engine, user, "perform_iq_test", {"score": 85})
        assert result.current_step_id == "interview_step"
        assert result.current_task_id == "schedule_interview"
        assert result.status == "in_progress"

    def test_step_3_schedule_interview_advances_within_step(self, engine):
        user = _advance_to_iq(engine)
        user = _submit(engine, user, "perform_iq_test", {"score": 85})
        result = _submit(engine, user, "schedule_interview", {"interview_date": "2026-05-10"})
        # Task-level routing stays within interview_step.
        assert result.current_step_id == "interview_step"
        assert result.current_task_id == "perform_interview"
        assert result.status == "in_progress"

    def test_step_4_interview_pass_advances_to_sign_contract_step(self, engine):
        user = _advance_to_interview(engine)
        result = _submit(engine, user, "perform_interview", {"decision": "passed_interview"})
        assert result.current_step_id == "sign_contract_step"
        assert result.current_task_id == "upload_id"
        assert result.status == "in_progress"

    def test_step_5_upload_id_advances_within_step(self, engine):
        user = _advance_to_sign_contract_step(engine)
        result = _submit(engine, user, "upload_id", {"passport_number": "AB987654"})
        assert result.current_step_id == "sign_contract_step"
        assert result.current_task_id == "sign_contract"
        assert result.status == "in_progress"

    def test_step_6_sign_contract_advances_to_payment_step(self, engine):
        user = _advance_to_sign_contract_step(engine)
        user = _submit(engine, user, "upload_id", {"passport_number": "AB987654"})
        result = _submit(engine, user, "sign_contract", {})
        assert result.current_step_id == "payment_step"
        assert result.current_task_id == "submit_payment"
        assert result.status == "in_progress"

    def test_step_7_payment_advances_to_join_slack_step(self, engine):
        user = _advance_to_sign_contract_step(engine)
        user = _submit(engine, user, "upload_id", {"passport_number": "AB987654"})
        user = _submit(engine, user, "sign_contract", {})
        result = _submit(engine, user, "submit_payment", {"payment_id": "pay_abc"})
        assert result.current_step_id == "join_slack_step"
        assert result.current_task_id == "join_slack"
        assert result.status == "in_progress"

    def test_step_8_join_slack_resolves_accepted(self, engine):
        user = _advance_to_join_slack(engine)
        result = _submit(engine, user, "join_slack", {"email": "alice@example.com"})
        assert result.status == "accepted"

    def test_full_happy_path_yields_accepted(self, engine):
        """End-to-end smoke test: every step in sequence."""
        user = _initial_user()

        user = _submit(engine, user, "submit_personal_details", {
            "first_name": "Carol", "last_name": "White", "email": "carol@test.com",
        })
        user = _submit(engine, user, "perform_iq_test", {"score": 90})
        user = _submit(engine, user, "schedule_interview", {"interview_date": "2026-06-01"})
        user = _submit(engine, user, "perform_interview", {"decision": "passed_interview"})
        user = _submit(engine, user, "upload_id", {"passport_number": "CD112233"})
        user = _submit(engine, user, "sign_contract", {})
        user = _submit(engine, user, "submit_payment", {"payment_id": "pay_full_999"})
        user = _submit(engine, user, "join_slack", {"email": "carol@test.com"})

        assert user.status == "accepted"

    def test_context_accumulates_across_steps(self, engine):
        user = _initial_user()
        user = _submit(engine, user, "submit_personal_details", {
            "first_name": "Dave", "last_name": "Brown", "email": "dave@test.com",
        })
        # Personal details should be in the accumulated context.
        assert user.context["first_name"] == "Dave"
        assert user.context["email"] == "dave@test.com"

        user = _submit(engine, user, "perform_iq_test", {"score": 80})
        # Score from a later step is also accumulated.
        assert user.context["score"] == 80
        # Earlier data is preserved.
        assert user.context["first_name"] == "Dave"


# ---------------------------------------------------------------------------
# IQ Rejection Path
# ---------------------------------------------------------------------------


class TestIqRejectionPath:
    """Applicants who score at or below the threshold are rejected immediately."""

    def test_score_exactly_at_threshold_is_rejected(self, engine):
        user = _advance_to_iq(engine)
        result = _submit(engine, user, "perform_iq_test", {"score": 75})
        assert result.status == "rejected"

    def test_score_one_below_threshold_is_rejected(self, engine):
        user = _advance_to_iq(engine)
        result = _submit(engine, user, "perform_iq_test", {"score": 74})
        assert result.status == "rejected"

    def test_score_50_is_rejected(self, engine):
        user = _advance_to_iq(engine)
        result = _submit(engine, user, "perform_iq_test", {"score": 50})
        assert result.status == "rejected"

    def test_score_zero_is_rejected(self, engine):
        user = _advance_to_iq(engine)
        result = _submit(engine, user, "perform_iq_test", {"score": 0})
        assert result.status == "rejected"

    def test_score_one_above_threshold_is_not_rejected(self, engine):
        # 76 > 75 → passes; applicant must NOT be rejected.
        user = _advance_to_iq(engine)
        result = _submit(engine, user, "perform_iq_test", {"score": 76})
        assert result.status != "rejected"
        assert result.current_step_id == "interview_step"

    def test_rejection_does_not_advance_step_or_task(self, engine):
        # A rejected user should have their status set; position is irrelevant
        # but must not point at the next step.
        user = _advance_to_iq(engine)
        result = _submit(engine, user, "perform_iq_test", {"score": 50})
        assert result.status == "rejected"
        # The applicant must not have been routed into interview_step.
        assert result.current_step_id != "interview_step"

# ---------------------------------------------------------------------------
# Interview Rejection Path
# ---------------------------------------------------------------------------


class TestInterviewRejectionPath:
    """Applicants who fail the interview are rejected at the task level."""

    def test_failed_decision_string_is_rejected(self, engine):
        user = _advance_to_interview(engine)
        result = _submit(engine, user, "perform_interview", {
            "decision": "failed_interview",
        })
        assert result.status == "rejected"

    def test_wrong_decision_string_is_rejected(self, engine):
        user = _advance_to_interview(engine)
        result = _submit(engine, user, "perform_interview", {
            "decision": "no_decision",
        })
        assert result.status == "rejected"

    def test_empty_decision_string_is_rejected(self, engine):
        user = _advance_to_interview(engine)
        result = _submit(engine, user, "perform_interview", {"decision": ""})
        assert result.status == "rejected"

    def test_uppercase_decision_is_rejected(self, engine):
        # Decision matching is case-sensitive.
        user = _advance_to_interview(engine)
        result = _submit(engine, user, "perform_interview", {
            "decision": "PASSED_INTERVIEW",
        })
        assert result.status == "rejected"

    def test_correct_decision_is_not_rejected(self, engine):
        user = _advance_to_interview(engine)
        result = _submit(engine, user, "perform_interview", {
            "decision": "passed_interview",
        })
        assert result.status != "rejected"
        assert result.current_step_id == "sign_contract_step"


# ---------------------------------------------------------------------------
# Validator Enforcement
# ---------------------------------------------------------------------------


class TestValidatorEnforcement:
    """Missing payload keys must be rejected before any routing occurs."""

    def test_personal_details_missing_email_raises(self, engine):
        user = _initial_user()
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "submit_personal_details", {
                "first_name": "Eve",
                "last_name": "Adams",
                # "email" intentionally omitted
            })

    def test_personal_details_missing_first_name_raises(self, engine):
        user = _initial_user()
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "submit_personal_details", {
                "last_name": "Adams",
                "email": "eve@test.com",
            })

    def test_personal_details_empty_payload_raises(self, engine):
        user = _initial_user()
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "submit_personal_details", {})

    def test_iq_test_missing_score_raises(self, engine):
        user = _advance_to_iq(engine)
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "perform_iq_test", {"wrong_key": "oops"})

    def test_iq_test_empty_payload_raises(self, engine):
        user = _advance_to_iq(engine)
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "perform_iq_test", {})

    def test_schedule_interview_missing_date_raises(self, engine):
        user = _advance_to_iq(engine)
        user = _submit(engine, user, "perform_iq_test", {"score": 80})
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "schedule_interview", {"no_date": True})

    def test_perform_interview_missing_decision_raises(self, engine):
        user = _advance_to_interview(engine)
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "perform_interview", {"notes": "good candidate"})

    def test_upload_id_missing_passport_raises(self, engine):
        user = _advance_to_sign_contract_step(engine)
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "upload_id", {"id": "wrong_key"})

    def test_payment_missing_payment_id_raises(self, engine):
        user = _advance_to_sign_contract_step(engine)
        user = _submit(engine, user, "upload_id", {"passport_number": "XY000111"})
        user = _submit(engine, user, "sign_contract", {})
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "submit_payment", {"amount": 999})

    def test_join_slack_missing_email_raises(self, engine):
        user = _advance_to_join_slack(engine)
        with pytest.raises(ValueError, match="Payload failed validation"):
            _submit(engine, user, "join_slack", {"team": "engineering"})

    def test_validator_rejection_does_not_advance_user(self, engine):
        # The user's position must not change when validation fails.
        user = _advance_to_iq(engine)
        original_step = user.current_step_id
        original_task = user.current_task_id
        with pytest.raises(ValueError):
            _submit(engine, user, "perform_iq_test", {})
        # Original user snapshot is unchanged (immutability guarantee).
        assert user.current_step_id == original_step
        assert user.current_task_id == original_task


# ---------------------------------------------------------------------------
# Out-of-order submission guard
# ---------------------------------------------------------------------------


class TestOutOfOrderSubmission:
    """process_webhook must reject submissions for the wrong task."""

    def test_submitting_wrong_task_raises_value_error(self, engine):
        # User is on perform_iq_test but submits for schedule_interview.
        user = _advance_to_iq(engine)
        with pytest.raises(ValueError, match="Webhook targets task"):
            _submit(engine, user, "schedule_interview", {"interview_date": "2026-01-01"})

    def test_submitting_for_completed_task_raises_value_error(self, engine):
        # User has advanced past submit_personal_details; re-submitting it
        # must be rejected.
        user = _advance_to_iq(engine)
        with pytest.raises(ValueError, match="Webhook targets task"):
            _submit(engine, user, "submit_personal_details", {
                "first_name": "Alice", "last_name": "Smith", "email": "a@b.com",
            })
