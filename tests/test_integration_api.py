"""
End-to-End integration tests for the Maestro-Flow API.

These tests drive the full application stack — HTTP layer, engine routing,
and in-memory store — via TestClient without any mocking. Every request
goes through the same code path a real client would hit.

A ``clear_store`` fixture resets the shared ``user_store`` singleton before
and after each test to guarantee isolation between scenarios.

Scenarios covered
─────────────────
  Happy Path         — full admissions journey from POST /users to
                       status "accepted" via eight consecutive PUT requests.
  IQ Rejection Path  — score at or below the threshold halts the journey
                       with status "rejected" immediately after the IQ task.
  Interview Rejection— passes IQ but fails interview; status "rejected".
  Out-of-order guard — submitting the wrong task is rejected with 400.
  Progress tracking  — GET /flow total_steps can be used to compute progress;
                       GET /users/{id}/current confirms position after each step.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.core.store import user_store
from app.main import app


client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Store isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_store():
    """Reset the shared singleton store before and after every test."""
    user_store._users.clear()
    yield
    user_store._users.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_users(email: str = "applicant@test.com") -> str:
    """Register a new user and return their user_id."""
    resp = client.post("/users", json={"email": email})
    assert resp.status_code == 201, resp.text
    return resp.json()["user_id"]


def _put_complete(user_id: str, task_id: str, data: dict | None = None) -> Response:
    """Submit a task completion and return the full JSON response body."""
    resp = client.put(
        "/tasks/complete",
        json={
            "user_id": user_id,
            "step_id": "e2e",
            "task_id": task_id,
            "payload": data or {},
        },
    )
    return resp


def _get_status(user_id: str) -> str:
    resp = client.get(f"/users/{user_id}/status")
    assert resp.status_code == 200, resp.text
    return resp.json()["status"]


def _get_current(user_id: str) -> dict:
    resp = client.get(f"/users/{user_id}/current")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Happy Path — full end-to-end journey
# ---------------------------------------------------------------------------


class TestHappyPathE2E:
    """Complete admissions journey; final status must be 'accepted'."""

    def test_post_users_creates_applicant(self):
        user_id = _post_users("happy@test.com")
        assert user_id is not None and len(user_id) > 0

    def test_new_user_status_is_in_progress(self):
        user_id = _post_users()
        assert _get_status(user_id) == "in_progress"

    def test_new_user_starts_at_personal_details(self):
        user_id = _post_users()
        pos = _get_current(user_id)
        assert pos["current_step_id"] == "personal_details_step"
        assert pos["current_task_id"] == "submit_personal_details"

    def test_step1_personal_details_advances_to_iq(self):
        user_id = _post_users()
        resp = _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step_id"] == "iq_step"
        assert data["current_task_id"] == "perform_iq_test"
        assert data["status"] == "in_progress"

    def test_step2_iq_pass_advances_to_interview(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        resp = _put_complete(user_id, "perform_iq_test", {"score": 88})
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step_id"] == "interview_step"
        assert data["current_task_id"] == "schedule_interview"

    def test_step3_schedule_interview_advances_to_perform(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 88})
        resp = _put_complete(user_id, "schedule_interview", {
            "interview_date": "2026-05-20",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step_id"] == "interview_step"
        assert data["current_task_id"] == "perform_interview"

    def test_step4_interview_pass_advances_to_sign_contract(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 88})
        _put_complete(user_id, "schedule_interview", {"interview_date": "2026-05-20"})
        resp = _put_complete(user_id, "perform_interview", {
            "decision": "passed_interview",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step_id"] == "sign_contract_step"
        assert data["current_task_id"] == "upload_id"

    def test_step5_upload_id_advances_to_sign_contract_task(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 88})
        _put_complete(user_id, "schedule_interview", {"interview_date": "2026-05-20"})
        _put_complete(user_id, "perform_interview", {"decision": "passed_interview"})
        resp = _put_complete(user_id, "upload_id", {"passport_number": "AB123456"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_task_id"] == "sign_contract"

    def test_step6_sign_contract_advances_to_payment(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 88})
        _put_complete(user_id, "schedule_interview", {"interview_date": "2026-05-20"})
        _put_complete(user_id, "perform_interview", {"decision": "passed_interview"})
        _put_complete(user_id, "upload_id", {"passport_number": "AB123456"})
        resp = _put_complete(user_id, "sign_contract", {})
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step_id"] == "payment_step"

    def test_step7_payment_advances_to_slack(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 88})
        _put_complete(user_id, "schedule_interview", {"interview_date": "2026-05-20"})
        _put_complete(user_id, "perform_interview", {"decision": "passed_interview"})
        _put_complete(user_id, "upload_id", {"passport_number": "AB123456"})
        _put_complete(user_id, "sign_contract", {})
        resp = _put_complete(user_id, "submit_payment", {"payment_id": "pay_e2e_001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step_id"] == "join_slack_step"

    def test_step8_join_slack_resolves_accepted(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 88})
        _put_complete(user_id, "schedule_interview", {"interview_date": "2026-05-20"})
        _put_complete(user_id, "perform_interview", {"decision": "passed_interview"})
        _put_complete(user_id, "upload_id", {"passport_number": "AB123456"})
        _put_complete(user_id, "sign_contract", {})
        _put_complete(user_id, "submit_payment", {"payment_id": "pay_e2e_001"})
        resp = _put_complete(user_id, "join_slack", {"email": "alice@test.com"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    def test_full_happy_path_status_endpoint_returns_accepted(self):
        """End-to-end smoke test: submit all eight tasks and verify via GET /status."""
        user_id = _post_users("e2e_happy@test.com")

        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Bob", "last_name": "Baker", "email": "bob@e2e.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 95})
        _put_complete(user_id, "schedule_interview", {"interview_date": "2026-06-10"})
        _put_complete(user_id, "perform_interview", {"decision": "passed_interview"})
        _put_complete(user_id, "upload_id", {"passport_number": "CD987654"})
        _put_complete(user_id, "sign_contract", {})
        _put_complete(user_id, "submit_payment", {"payment_id": "pay_smoke"})
        _put_complete(user_id, "join_slack", {"email": "bob@e2e.com"})

        assert _get_status(user_id) == "accepted"

    def test_context_persists_across_steps(self):
        """Payload data from earlier steps is visible in the context after later steps."""
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Carol",
            "last_name": "Chen",
            "email": "carol@test.com",
        })
        resp = _put_complete(user_id, "perform_iq_test", {"score": 80})
        context = resp.json()["context"]
        # Personal details payload was merged into context at step 1.
        assert context.get("first_name") == "Carol"
        # IQ score from step 2 is also present.
        assert context.get("score") == 80

    def test_multiple_independent_users_do_not_interfere(self):
        """Two applicants progressing simultaneously must not share state."""
        id_a = _post_users("user_a@test.com")
        id_b = _post_users("user_b@test.com")

        # Advance user A only.
        _put_complete(id_a, "submit_personal_details", {
            "first_name": "A", "last_name": "Ace", "email": "a@test.com",
        })

        # User B must still be at the starting position.
        pos_b = _get_current(id_b)
        assert pos_b["current_step_id"] == "personal_details_step"
        assert pos_b["current_task_id"] == "submit_personal_details"


# ---------------------------------------------------------------------------
# IQ Rejection Path
# ---------------------------------------------------------------------------


class TestIqRejectionE2E:
    def test_score_at_threshold_is_rejected(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Dave", "last_name": "Doe", "email": "dave@test.com",
        })
        resp = _put_complete(user_id, "perform_iq_test", {"score": 75})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_score_below_threshold_is_rejected(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Eve", "last_name": "Ellis", "email": "eve@test.com",
        })
        resp = _put_complete(user_id, "perform_iq_test", {"score": 40})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_status_endpoint_returns_rejected_after_iq_fail(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Frank", "last_name": "Fox", "email": "frank@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 60})
        assert _get_status(user_id) == "rejected"

    def test_score_one_above_threshold_is_not_rejected(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Gina", "last_name": "Grant", "email": "gina@test.com",
        })
        resp = _put_complete(user_id, "perform_iq_test", {"score": 76})
        assert resp.json()["status"] == "in_progress"
        assert resp.json()["current_step_id"] == "interview_step"

# ---------------------------------------------------------------------------
# Interview Rejection Path
# ---------------------------------------------------------------------------


class TestInterviewRejectionE2E:
    def _reach_interview(self) -> str:
        """Create a user and advance them to perform_interview."""
        user_id = _post_users("interview@test.com")
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Hank", "last_name": "Hill", "email": "hank@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 85})
        _put_complete(user_id, "schedule_interview", {"interview_date": "2026-07-01"})
        return user_id

    def test_failed_interview_decision_is_rejected(self):
        user_id = self._reach_interview()
        resp = _put_complete(user_id, "perform_interview", {
            "decision": "failed_interview",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_wrong_decision_string_is_rejected(self):
        user_id = self._reach_interview()
        resp = _put_complete(user_id, "perform_interview", {
            "decision": "PASSED_INTERVIEW",  # wrong case
        })
        assert resp.json()["status"] == "rejected"

    def test_status_endpoint_returns_rejected_after_interview_fail(self):
        user_id = self._reach_interview()
        _put_complete(user_id, "perform_interview", {"decision": "no"})
        assert _get_status(user_id) == "rejected"

    def test_correct_decision_is_not_rejected(self):
        user_id = self._reach_interview()
        resp = _put_complete(user_id, "perform_interview", {
            "decision": "passed_interview",
        })
        assert resp.json()["status"] != "rejected"
        assert resp.json()["current_step_id"] == "sign_contract_step"


# ---------------------------------------------------------------------------
# Out-of-order submission guard
# ---------------------------------------------------------------------------


class TestOutOfOrderE2E:
    def test_submitting_future_task_returns_400(self):
        user_id = _post_users()
        # User is at submit_personal_details; jumping to perform_iq_test must fail.
        resp = _put_complete(user_id, "perform_iq_test", {"score": 90})
        assert resp.status_code == 400

    def test_submitting_completed_task_again_returns_400(self):
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Ian", "last_name": "Irwin", "email": "ian@test.com",
        })
        # User has already advanced past submit_personal_details.
        resp = _put_complete(user_id, "submit_personal_details", {
            "first_name": "Ian", "last_name": "Irwin", "email": "ian@test.com",
        })
        assert resp.status_code == 400

    def test_position_unchanged_after_out_of_order_rejection(self):
        user_id = _post_users()
        # Attempt an invalid submission.
        _put_complete(user_id, "perform_iq_test", {"score": 90})
        # User must still be at the starting position.
        pos = _get_current(user_id)
        assert pos["current_task_id"] == "submit_personal_details"


# ---------------------------------------------------------------------------
# GET /flow used for progress tracking
# ---------------------------------------------------------------------------


class TestProgressTrackingE2E:
    def test_flow_provides_total_steps_for_progress_bar(self):
        user_id = _post_users()
        # Create the user and read the flow in a single session.
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Jane", "last_name": "Jay", "email": "jane@test.com",
        })
        flow = client.get("/flow").json()
        pos = _get_current(user_id)

        step_ids = [s["id"] for s in flow["ordered_steps"]]
        current_index = step_ids.index(pos["current_step_id"])

        # After completing step 1, the user is on step index 1 (iq_step).
        assert current_index == 1
        assert flow["total_steps"] == 6
        # Frontend can compute "Step 2 of 6".
        assert f"Step {current_index + 1} of {flow['total_steps']}" == "Step 2 of 6"

    def test_user_aware_flow_returns_200_with_matching_user_id(self):
        # After completing personal details the user has context data.
        # GET /flow?user_id=... must return 200 and echo the correct user_id.
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Sam", "last_name": "Quinn", "email": "sam@test.com",
        })
        resp = client.get("/flow", params={"user_id": user_id})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == user_id

    def test_user_aware_flow_total_steps_reflects_happy_path(self):
        # The current graph has no conditional branching that adds steps, so
        # the user-aware total_steps must remain 6 regardless of how far
        # along the happy path the user has progressed.
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Sam", "last_name": "Quinn", "email": "sam@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 90})
        flow = client.get("/flow", params={"user_id": user_id}).json()
        assert flow["total_steps"] == 6

    def test_user_aware_flow_step_order_is_consistent_with_global_flow(self):
        # The ordered step IDs returned by the user-aware endpoint must match
        # those of the anonymous global endpoint so the frontend can compute
        # a "Step X of Y" indicator purely from context index.
        user_id = _post_users()
        _put_complete(user_id, "submit_personal_details", {
            "first_name": "Sam", "last_name": "Quinn", "email": "sam@test.com",
        })
        _put_complete(user_id, "perform_iq_test", {"score": 90})

        global_step_ids = [
            s["id"] for s in client.get("/flow").json()["ordered_steps"]
        ]
        user_step_ids = [
            s["id"]
            for s in client.get("/flow", params={"user_id": user_id}).json()["ordered_steps"]
        ]
        assert user_step_ids == global_step_ids
