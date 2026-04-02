"""
Static workflow graph.

This module is the pure routing graph: it imports validators from
``app.core.validators`` and condition factories from
``app.core.conditions``, then assembles the FLOW_TASKS and FLOW_STEPS
registries that are injected into WorkflowEngine at startup.

"""

from typing import Dict

from datetime import datetime, timedelta

from app.core.conditions import (
    make_interview_success_condition,
    make_score_success_condition,
    make_max_attempts_condition
)
from app.core.validators import (
    validate_iq_score,
    validate_join_slack,
    validate_payment,
    validate_perform_interview,
    validate_personal_details,
    validate_schedule_interview,
    validate_upload_id,
)
from app.models.schemas import Outcome, StepNode, TaskNode

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Minimum IQ score required to pass directly to the interview stage.
MIN_PASSING_IQ_SCORE: int = 75

# to indicate a successful interview outcome.
PASSED_INTERVIEW_STATUS: str = "passed_interview"

# ---------------------------------------------------------------------------
# Entry point identifiers
# ---------------------------------------------------------------------------

STARTING_STEP_ID: str = "personal_details_step"
STARTING_TASK_ID: str = "submit_personal_details"

# ---------------------------------------------------------------------------
# Task nodes
# ---------------------------------------------------------------------------

FLOW_TASKS: Dict[str, TaskNode] = {
    # ------------------------------------------------------------------
    # Step: personal_details_step
    # ------------------------------------------------------------------
    "submit_personal_details": TaskNode(
        id="submit_personal_details",
        name="Submit Personal Details",
        validator=validate_personal_details,
        # Empty next_tasks — always falls through to personal_details_step's
        # next_steps,
        next_tasks=[],
        example_payload={
            "first_name": "Salim",
            "last_name": "Tuama",
            "email": "SalimTuama@gmail.com"
        }
    ),
    # ------------------------------------------------------------------
    # Step: iq_step
    # ------------------------------------------------------------------
    "perform_iq_test": TaskNode(
        id="perform_iq_test",
        name="Perform IQ Test",
        validator=validate_iq_score,
        next_tasks=[
            # 1. Does the score pass? (Success -> Progress to the next step)
            Outcome(
                condition=make_score_success_condition(MIN_PASSING_IQ_SCORE),
            ),
            # 2. Otherwise: Did not pass -> Immediate Rejection
            Outcome(
                condition=None,
                status="rejected",
            ),
        ],
        example_payload={"score": 85}
    ),
    # ------------------------------------------------------------------
    # Step: interview_step
    # ------------------------------------------------------------------
    "schedule_interview": TaskNode(
        id="schedule_interview",
        name="Schedule Interview",
        validator=validate_schedule_interview,
        next_tasks=[
            # Unconditional: always advance to the interview task.
            Outcome(
                condition=None,
                next_task_id="perform_interview",
            ),
        ],
        example_payload={"interview_date": (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat()}  
    ),
    "perform_interview": TaskNode(
        id="perform_interview",
        name="Perform Interview",
        validator=validate_perform_interview,
        next_tasks=[
            # Passing decision: condition matches but all routing fields are
            # None — explicit fallthrough signal. The engine escalates to
            # interview_step's next_steps, which advances unconditionally
            # to sign_contract_step.
            Outcome(
                condition=make_interview_success_condition(PASSED_INTERVIEW_STATUS),
            ),
            # Unconditional catch-all: decision is absent or != PASSED_INTERVIEW_STATUS.
            # Reached only when the success condition above did not match.
            Outcome(
                condition=None,
                status="rejected",
            ),
        ],
        example_payload={"decision": "passed_interview"}
    ),
    # ------------------------------------------------------------------
    # Step: sign_contract_step
    # ------------------------------------------------------------------
    "upload_id": TaskNode(
        id="upload_id",
        name="Upload ID",
        validator=validate_upload_id,
        next_tasks=[
            # Unconditional: always advance to contract signing.
            Outcome(
                condition=None,
                next_task_id="sign_contract",
            ),
        ],
        example_payload={"passport_number": "123456789"}
    ),
    "sign_contract": TaskNode(
        id="sign_contract",
        name="Sign Contract",
        validator=None,
        # Empty next_tasks — falls through to sign_contract_step's next_steps,
        # which advances unconditionally to payment_step.
        next_tasks=[],
        example_payload={}
    ),
    # ------------------------------------------------------------------
    # Step: payment_step
    # ------------------------------------------------------------------
    "submit_payment": TaskNode(
        id="submit_payment",
        name="Submit Payment",
        validator=validate_payment,
        # Empty next_tasks — falls through to payment_step's next_steps,
        # which advances unconditionally to join_slack_step.
        next_tasks=[],
        example_payload={"payment_id": "pay_abc123"}
    ),
    # ------------------------------------------------------------------
    # Step: join_slack_step
    # ------------------------------------------------------------------
    "join_slack": TaskNode(
        id="join_slack",
        name="Join Slack",
        validator=validate_join_slack,
        # Empty next_tasks — falls through to join_slack_step's next_steps,
        # which resolves the journey to "accepted".
        next_tasks=[],
        example_payload={"email": "My_Email@gmail.com"}
    ),

}

# ---------------------------------------------------------------------------
# Step nodes
# ---------------------------------------------------------------------------

FLOW_STEPS: Dict[str, StepNode] = {
    "personal_details_step": StepNode(
        id="personal_details_step",
        name="Personal Details",
        first_task_id="submit_personal_details",
        next_steps=[
            Outcome(condition=None, next_step_id="iq_step"),
        ],
    ),
    "iq_step": StepNode(
        id="iq_step",
        name="IQ Assessment",
        first_task_id="perform_iq_test",
        next_steps=[
            # Triggered when perform_iq_test falls through (score > 75).
            Outcome(condition=None, next_step_id="interview_step"),
        ],
    ),
    "interview_step": StepNode(
        id="interview_step",
        name="Interview",
        first_task_id="schedule_interview",
        next_steps=[
            # Triggered when perform_interview falls through (interview passed).
            Outcome(condition=None, next_step_id="sign_contract_step"),
        ],
    ),
    "sign_contract_step": StepNode(
        id="sign_contract_step",
        name="Sign Contract",
        first_task_id="upload_id",
        next_steps=[
            Outcome(condition=None, next_step_id="payment_step"),
        ],
    ),
    "payment_step": StepNode(
        id="payment_step",
        name="Payment",
        first_task_id="submit_payment",
        next_steps=[
            Outcome(condition=None, next_step_id="join_slack_step"),
        ],
    ),
    "join_slack_step": StepNode(
        id="join_slack_step",
        name="Join Slack",
        first_task_id="join_slack",
        next_steps=[
            # Terminal: completing this step accepts the applicant.
            Outcome(condition=None, status="accepted"),
        ],
    ),    

}



