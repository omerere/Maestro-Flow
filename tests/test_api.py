"""
API layer tests using FastAPI's TestClient.

Each test class covers one endpoint. A ``clear_store`` fixture with
``autouse=True`` resets the shared ``user_store`` singleton before and
after every test, preventing state leakage between cases.

The ``TestClient`` drives the full ASGI stack — exception handlers,
request parsing, Pydantic validation, and response serialisation are
all exercised exactly as they are in production.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.flow_config import STARTING_STEP_ID, STARTING_TASK_ID
from app.core.store import user_store
from app.main import app
from httpx import Response

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Store isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_store():
    """Clear the singleton store before and after every test."""
    user_store._users.clear()
    yield
    user_store._users.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user(email: str = "test@example.com") -> str:
    """POST /users and return the created user_id."""
    resp = client.post("/users", json={"email": email})
    assert resp.status_code == 201
    return resp.json()["user_id"]


def _complete_task(user_id: str, task_id: str, data: dict | None = None) -> Response:
    """PUT /tasks/complete for the given task and return the response JSON."""
    body = {
        "user_id": user_id,
        "step_id": "irrelevant",
        "task_id": task_id,
        "payload": data or {},
    }
    return client.put("/tasks/complete", json=body)


# ---------------------------------------------------------------------------
# POST /users
# ---------------------------------------------------------------------------


class TestPostUsers:
    def test_returns_201_created(self):
        resp = client.post("/users", json={"email": "alice@test.com"})
        assert resp.status_code == 201

    def test_response_contains_user_id(self):
        resp = client.post("/users", json={"email": "alice@test.com"})
        assert "user_id" in resp.json()

    def test_user_id_is_non_empty_string(self):
        resp = client.post("/users", json={"email": "alice@test.com"})
        assert isinstance(resp.json()["user_id"], str)
        assert len(resp.json()["user_id"]) > 0

    def test_two_requests_produce_different_user_ids(self):
        id_a = client.post("/users", json={"email": "a@test.com"}).json()["user_id"]
        id_b = client.post("/users", json={"email": "b@test.com"}).json()["user_id"]
        assert id_a != id_b

    def test_missing_email_returns_422(self):
        resp = client.post("/users", json={})
        assert resp.status_code == 422

    def test_missing_body_returns_422(self):
        resp = client.post("/users")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /flow
# ---------------------------------------------------------------------------


class TestGetFlow:
    def test_returns_200(self):
        resp = client.get("/flow")
        assert resp.status_code == 200

    def test_response_has_total_steps_key(self):
        data = client.get("/flow").json()
        assert "total_steps" in data

    def test_response_has_ordered_steps_key(self):
        data = client.get("/flow").json()
        assert "ordered_steps" in data

    def test_total_steps_is_six(self):
        # The admissions graph has 6 steps on the happy path.
        data = client.get("/flow").json()
        assert data["total_steps"] == 6

    def test_ordered_steps_length_matches_total_steps(self):
        data = client.get("/flow").json()
        assert len(data["ordered_steps"]) == data["total_steps"]

    def test_first_step_is_personal_details(self):
        data = client.get("/flow").json()
        assert data["ordered_steps"][0]["id"] == STARTING_STEP_ID

    def test_last_step_is_join_slack(self):
        data = client.get("/flow").json()
        assert data["ordered_steps"][-1]["id"] == "join_slack_step"

    def test_each_step_has_id_name_tasks(self):
        data = client.get("/flow").json()
        for step in data["ordered_steps"]:
            assert "id" in step
            assert "name" in step
            assert "tasks" in step

    def test_each_task_has_id_and_name(self):
        data = client.get("/flow").json()
        for step in data["ordered_steps"]:
            for task in step["tasks"]:
                assert "id" in task
                assert "name" in task

    def test_steps_are_in_correct_order(self):
        expected = [
            "personal_details_step",
            "iq_step",
            "interview_step",
            "sign_contract_step",
            "payment_step",
            "join_slack_step",
        ]
        step_ids = [s["id"] for s in client.get("/flow").json()["ordered_steps"]]
        assert step_ids == expected

    def test_interview_step_contains_two_tasks(self):
        data = client.get("/flow").json()
        interview = next(s for s in data["ordered_steps"] if s["id"] == "interview_step")
        assert len(interview["tasks"]) == 2

    def test_sign_contract_step_contains_two_tasks(self):
        data = client.get("/flow").json()
        sign = next(s for s in data["ordered_steps"] if s["id"] == "sign_contract_step")
        assert len(sign["tasks"]) == 2

    def test_total_task_count_is_eight(self):
        data = client.get("/flow").json()
        total = sum(len(s["tasks"]) for s in data["ordered_steps"])
        assert total == 8

    def test_response_is_identical_on_repeated_calls(self):
        # Flow is static; calling twice must produce the same result.
        a = client.get("/flow").json()
        b = client.get("/flow").json()
        assert a == b

    # -- user_id query parameter ------------------------------------------

    def test_no_user_id_param_returns_null_user_id_in_response(self):
        # Global (unauthenticated) flow must carry user_id: null.
        data = client.get("/flow").json()
        assert data["user_id"] is None

    def test_valid_user_id_param_returns_200_and_echoes_user_id(self):
        # When a real user_id is supplied the response is 200 and the
        # returned user_id matches the one we registered.
        uid = _create_user()
        resp = client.get("/flow", params={"user_id": uid})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == uid

    def test_unknown_user_id_param_returns_404(self):
        # A user_id that was never registered must trigger the UserNotFoundError
        # handler and return 404.
        resp = client.get("/flow", params={"user_id": "invalid_ghost_id"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /users/{user_id}/current
# ---------------------------------------------------------------------------


class TestGetUserCurrent:
    def test_returns_200_for_existing_user(self):
        user_id = _create_user()
        resp = client.get(f"/users/{user_id}/current")
        assert resp.status_code == 200

    def test_returns_starting_step_id(self):
        user_id = _create_user()
        data = client.get(f"/users/{user_id}/current").json()
        assert data["current_step_id"] == STARTING_STEP_ID

    def test_returns_starting_task_id(self):
        user_id = _create_user()
        data = client.get(f"/users/{user_id}/current").json()
        assert data["current_task_id"] == STARTING_TASK_ID

    def test_returns_404_for_unknown_user_id(self):
        resp = client.get("/users/nonexistent-id/current")
        assert resp.status_code == 404

    def test_404_response_has_detail_key(self):
        resp = client.get("/users/ghost/current")
        assert "detail" in resp.json()

    def test_position_updates_after_task_completion(self):
        user_id = _create_user()
        _complete_task(user_id, "submit_personal_details", {
            "first_name": "Alice", "last_name": "Smith", "email": "alice@test.com",
        })
        data = client.get(f"/users/{user_id}/current").json()
        # After personal details, user should be on the IQ step.
        assert data["current_step_id"] == "iq_step"
        assert data["current_task_id"] == "perform_iq_test"


# ---------------------------------------------------------------------------
# PUT /tasks/complete
# ---------------------------------------------------------------------------


class TestPutTasksComplete:
    def test_returns_200_for_valid_submission(self):
        user_id = _create_user()
        resp = _complete_task(user_id, "submit_personal_details", {
            "first_name": "Bob", "last_name": "Jones", "email": "bob@test.com",
        })
        assert resp.status_code == 200

    def test_response_contains_updated_user_state(self):
        user_id = _create_user()
        resp = _complete_task(user_id, "submit_personal_details", {
            "first_name": "Bob", "last_name": "Jones", "email": "bob@test.com",
        })
        data = resp.json()
        assert "current_step_id" in data
        assert "current_task_id" in data
        assert "status" in data
        assert "context" in data

    def test_state_advances_after_successful_completion(self):
        user_id = _create_user()
        data = _complete_task(user_id, "submit_personal_details", {
            "first_name": "Bob", "last_name": "Jones", "email": "bob@test.com",
        }).json()
        assert data["current_step_id"] == "iq_step"

    def test_returns_400_for_missing_required_payload_keys(self):
        user_id = _create_user()
        # "email" is required by validate_personal_details.
        resp = _complete_task(user_id, "submit_personal_details", {
            "first_name": "Bob",
            "last_name": "Jones",
            # "email" intentionally omitted
        })
        assert resp.status_code == 400

    def test_400_response_has_detail_key(self):
        user_id = _create_user()
        resp = _complete_task(user_id, "submit_personal_details", {})
        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_returns_400_for_empty_payload(self):
        user_id = _create_user()
        resp = _complete_task(user_id, "submit_personal_details", {})
        assert resp.status_code == 400

    def test_returns_400_when_targeting_wrong_task(self):
        user_id = _create_user()
        # User is on submit_personal_details; submitting for perform_iq_test
        # must be rejected.
        resp = _complete_task(user_id, "perform_iq_test", {"score": 80})
        assert resp.status_code == 400

    def test_returns_404_for_unknown_user_id(self):
        resp = _complete_task("no-such-user", "submit_personal_details", {
            "first_name": "X", "last_name": "Y", "email": "x@y.com",
        })
        assert resp.status_code == 404

    def test_returns_422_for_missing_body_fields(self):
        # TaskPayload requires user_id, step_id, task_id, payload.
        resp = client.put("/tasks/complete", json={"user_id": "x"})
        assert resp.status_code == 422

    def test_store_is_updated_after_completion(self):
        user_id = _create_user()
        _complete_task(user_id, "submit_personal_details", {
            "first_name": "Carol", "last_name": "White", "email": "carol@test.com",
        })
        # GET /current must reflect the engine's routing decision.
        pos = client.get(f"/users/{user_id}/current").json()
        assert pos["current_step_id"] == "iq_step"

    def test_status_changes_to_rejected_after_iq_fail(self):
        user_id = _create_user()
        _complete_task(user_id, "submit_personal_details", {
            "first_name": "Fred", "last_name": "Gray", "email": "fred@test.com",
        })
        # Score below threshold rejects immediately.
        _complete_task(user_id, "perform_iq_test", {"score": 50})
        data = client.get(f"/users/{user_id}/status").json()
        assert data["status"] == "rejected"

    def test_iq_pass_resolves_to_in_progress(self):
        user_id = _create_user()
        _complete_task(user_id, "submit_personal_details", {
            "first_name": "Eve", "last_name": "Fox", "email": "eve@test.com",
        })
        data = _complete_task(user_id, "perform_iq_test", {"score": 76}).json()
        assert data["status"] == "in_progress"
        assert data["current_step_id"] == "interview_step"


# ---------------------------------------------------------------------------
# GET /users/{user_id}/status
# ---------------------------------------------------------------------------


class TestGetUserStatus:
    def test_returns_200_for_existing_user(self):
        user_id = _create_user()
        resp = client.get(f"/users/{user_id}/status")
        assert resp.status_code == 200

    def test_initial_status_is_in_progress(self):
        user_id = _create_user()
        data = client.get(f"/users/{user_id}/status").json()
        assert data["status"] == "in_progress"

    def test_response_has_status_key(self):
        user_id = _create_user()
        data = client.get(f"/users/{user_id}/status").json()
        assert "status" in data

    def test_returns_404_for_unknown_user_id(self):
        resp = client.get("/users/does-not-exist/status")
        assert resp.status_code == 404

    def test_status_changes_to_rejected_after_iq_fail(self):
        user_id = _create_user()
        _complete_task(user_id, "submit_personal_details", {
            "first_name": "Fred", "last_name": "Gray", "email": "fred@test.com",
        })
        # 3 failed attempts are required before rejection.
        _complete_task(user_id, "perform_iq_test", {"score": 50})
        _complete_task(user_id, "perform_iq_test", {"score": 50})
        _complete_task(user_id, "perform_iq_test", {"score": 50})
        data = client.get(f"/users/{user_id}/status").json()
        assert data["status"] == "rejected"
