"""
Unit tests for all payload validator callables in app.core.validators.

Each validator is a pure function ``(payload: Dict[str, Any]) -> bool``.
These tests verify two invariants for every validator:

  1. Returns True when all required keys are present (valid payload).
  2. Returns False for empty payloads, missing required keys, or entirely
     wrong keys — regardless of any other data that may be present.

Tests are grouped by validator under a dedicated class so failures are
easy to locate in the pytest output.
"""

import pytest

from app.core.validators import (
    validate_iq_score,
    validate_join_slack,
    validate_payment,
    validate_perform_interview,
    validate_personal_details,
    validate_schedule_interview,
    validate_upload_id,
)


# ---------------------------------------------------------------------------
# validate_iq_score
# ---------------------------------------------------------------------------


class TestValidateIqScore:
    """Required key: "score"."""

    def test_returns_true_with_score_key(self):
        assert validate_iq_score({"score": 80}) is True

    def test_returns_true_when_score_is_zero(self):
        # score=0 is a valid submission; the key is present even if the
        # value itself would not pass the IQ threshold.
        assert validate_iq_score({"score": 0}) is True

    def test_returns_true_with_extra_keys(self):
        assert validate_iq_score({"score": 90, "user_id": "u1"}) is True

    def test_returns_true_when_score_is_negative(self):
        # Validators only check key presence, not value range.
        assert validate_iq_score({"score": -5}) is True

    def test_returns_false_for_empty_payload(self):
        assert validate_iq_score({}) is False

    def test_returns_false_for_wrong_key(self):
        assert validate_iq_score({"result": 80}) is False

    def test_returns_false_for_partial_key_name(self):
        assert validate_iq_score({"scor": 80}) is False

    def test_returns_false_when_only_unrelated_keys_present(self):
        assert validate_iq_score({"first_name": "Alice", "email": "a@b.com"}) is False


# ---------------------------------------------------------------------------
# validate_personal_details
# ---------------------------------------------------------------------------


class TestValidatePersonalDetails:
    """Required keys: "first_name", "last_name", "email"."""

    def test_returns_true_with_all_required_keys(self):
        assert validate_personal_details(
            {"first_name": "Alice", "last_name": "Smith", "email": "alice@example.com"}
        ) is True

    def test_returns_true_with_extra_keys(self):
        assert validate_personal_details(
            {
                "first_name": "Bob",
                "last_name": "Jones",
                "email": "bob@test.com",
                "phone": "+44-123",
            }
        ) is True

    def test_returns_false_for_empty_payload(self):
        assert validate_personal_details({}) is False

    def test_returns_false_when_first_name_missing(self):
        assert validate_personal_details(
            {"last_name": "Smith", "email": "alice@example.com"}
        ) is False

    def test_returns_false_when_last_name_missing(self):
        assert validate_personal_details(
            {"first_name": "Alice", "email": "alice@example.com"}
        ) is False

    def test_returns_false_when_email_missing(self):
        assert validate_personal_details(
            {"first_name": "Alice", "last_name": "Smith"}
        ) is False

    def test_returns_false_when_only_one_key_present(self):
        assert validate_personal_details({"first_name": "Alice"}) is False

    def test_returns_false_for_completely_wrong_keys(self):
        assert validate_personal_details(
            {"name": "Alice Smith", "mail": "alice@example.com"}
        ) is False


# ---------------------------------------------------------------------------
# validate_schedule_interview
# ---------------------------------------------------------------------------


class TestValidateScheduleInterview:
    """Required key: "interview_date"."""

    def test_returns_true_with_interview_date(self):
        assert validate_schedule_interview({"interview_date": "2026-05-01"}) is True

    def test_returns_true_with_extra_keys(self):
        assert validate_schedule_interview(
            {"interview_date": "2026-05-01", "slot": "AM", "location": "Zoom"}
        ) is True

    def test_returns_false_for_empty_payload(self):
        assert validate_schedule_interview({}) is False

    def test_returns_false_for_wrong_key(self):
        assert validate_schedule_interview({"date": "2026-05-01"}) is False

    def test_returns_false_for_partial_key_name(self):
        # Substring of the required key must not match.
        assert validate_schedule_interview({"interview": "2026-05-01"}) is False

    def test_returns_false_for_similar_but_incorrect_key(self):
        assert validate_schedule_interview({"interview_time": "09:00"}) is False


# ---------------------------------------------------------------------------
# validate_perform_interview
# ---------------------------------------------------------------------------


class TestValidatePerformInterview:
    """Required key: "decision"."""

    def test_returns_true_with_decision_key(self):
        assert validate_perform_interview({"decision": "passed_interview"}) is True

    def test_returns_true_for_non_passing_decision(self):
        # The validator only checks key presence, not value. This payload
        # would be rejected at the condition level, not the validator level.
        assert validate_perform_interview({"decision": "failed_interview"}) is True

    def test_returns_true_for_empty_decision_string(self):
        # Empty string is still a present key.
        assert validate_perform_interview({"decision": ""}) is True

    def test_returns_true_with_extra_keys(self):
        assert validate_perform_interview(
            {"decision": "passed_interview", "notes": "Strong candidate."}
        ) is True

    def test_returns_false_for_empty_payload(self):
        assert validate_perform_interview({}) is False

    def test_returns_false_for_wrong_key(self):
        assert validate_perform_interview({"result": "passed_interview"}) is False

    def test_returns_false_for_close_but_wrong_key(self):
        assert validate_perform_interview({"decisions": "passed_interview"}) is False


# ---------------------------------------------------------------------------
# validate_upload_id
# ---------------------------------------------------------------------------


class TestValidateUploadId:
    """Required key: "passport_number"."""

    def test_returns_true_with_passport_number(self):
        assert validate_upload_id({"passport_number": "AB123456"}) is True

    def test_returns_true_with_extra_keys(self):
        assert validate_upload_id(
            {"passport_number": "AB123456", "country": "UK", "expiry": "2030-01-01"}
        ) is True

    def test_returns_false_for_empty_payload(self):
        assert validate_upload_id({}) is False

    def test_returns_false_for_wrong_key(self):
        assert validate_upload_id({"id_number": "AB123456"}) is False

    def test_returns_false_for_partial_key_name(self):
        # "passport" alone is not the required key.
        assert validate_upload_id({"passport": "AB123456"}) is False

    def test_returns_false_for_similar_key(self):
        assert validate_upload_id({"passport_no": "AB123456"}) is False


# ---------------------------------------------------------------------------
# validate_payment
# ---------------------------------------------------------------------------


class TestValidatePayment:
    """Required key: "payment_id"."""

    def test_returns_true_with_payment_id(self):
        assert validate_payment({"payment_id": "pay_abc123"}) is True

    def test_returns_true_with_extra_keys(self):
        assert validate_payment(
            {"payment_id": "pay_abc123", "amount": 1500, "currency": "GBP"}
        ) is True

    def test_returns_false_for_empty_payload(self):
        assert validate_payment({}) is False

    def test_returns_false_for_wrong_key(self):
        assert validate_payment({"payment": "pay_abc123"}) is False

    def test_returns_false_for_transaction_id_key(self):
        # A common alternative naming must still be rejected.
        assert validate_payment({"transaction_id": "pay_abc123"}) is False

    def test_returns_false_for_partial_key_name(self):
        assert validate_payment({"payment_i": "pay_abc123"}) is False


# ---------------------------------------------------------------------------
# validate_join_slack
# ---------------------------------------------------------------------------


class TestValidateJoinSlack:
    """Required key: "email"."""

    def test_returns_true_with_email(self):
        assert validate_join_slack({"email": "alice@example.com"}) is True

    def test_returns_true_with_extra_keys(self):
        assert validate_join_slack(
            {"email": "alice@example.com", "team": "engineering", "role": "student"}
        ) is True

    def test_returns_true_for_empty_email_string(self):
        # Validator checks key presence; value validation is out of scope.
        assert validate_join_slack({"email": ""}) is True

    def test_returns_false_for_empty_payload(self):
        assert validate_join_slack({}) is False

    def test_returns_false_for_wrong_key(self):
        assert validate_join_slack({"address": "alice@example.com"}) is False

    def test_returns_false_for_partial_key_name(self):
        assert validate_join_slack({"mail": "alice@example.com"}) is False

    def test_returns_false_for_similar_key(self):
        assert validate_join_slack({"email_address": "alice@example.com"}) is False
