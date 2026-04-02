"""
Unit tests for condition factories in app.core.conditions and 
configuration constants in app.core.flow_config.

Covers:
  - Constant values (MIN_PASSING_IQ_SCORE, PASSED_INTERVIEW_STATUS, MAX_IQ_ATTEMPTS).
  - make_score_success_condition: boundary analysis, missing key, extra context,
    independent closures from separate factory invocations.
  - make_interview_success_condition: exact match, wrong string, case
    sensitivity, missing key, extra context, independent closures.
  - make_max_attempts_condition: boundary analysis on attempt counter, missing
    key defaults, payload independence, independent closures.

All condition callables accept (payload: Dict, context: Dict) -> bool.
"""

import pytest

from app.core.conditions import (
    make_interview_success_condition,
    make_max_attempts_condition,
    make_score_success_condition,
)

from app.core.flow_config import (
    MIN_PASSING_IQ_SCORE,
    PASSED_INTERVIEW_STATUS
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_min_passing_iq_score_is_75(self):
        assert MIN_PASSING_IQ_SCORE == 75

    def test_passed_interview_status_value(self):
        assert PASSED_INTERVIEW_STATUS == "passed_interview"

    def test_min_passing_iq_score_is_int(self):
        assert isinstance(MIN_PASSING_IQ_SCORE, int)

    def test_passed_interview_status_is_str(self):
        assert isinstance(PASSED_INTERVIEW_STATUS, str)
        


# ---------------------------------------------------------------------------
# make_score_success_condition
# ---------------------------------------------------------------------------


class TestMakeScoreSuccessCondition:
    """
    Boundary analysis for the score success condition.

    Configured with the production threshold (75):
      score > 75  → True   (pass)
      score == 75 → False  (fail — strictly greater than required)
      score < 75  → False  (fail)
    """

    @pytest.fixture
    def condition(self):
        """Production-configured condition: threshold = 75."""
        return make_score_success_condition(75)

    # --- Passing values ---

    def test_score_one_above_threshold_returns_true(self, condition):
        assert condition({"score": 76}, {}) is True

    def test_score_well_above_threshold_returns_true(self, condition):
        assert condition({"score": 100}, {}) is True

    def test_score_high_returns_true(self, condition):
        assert condition({"score": 150}, {}) is True

    # --- Failing values (boundary and below) ---

    def test_score_exactly_at_threshold_returns_false(self, condition):
        # Strictly greater than is required; equal does NOT pass.
        assert condition({"score": 75}, {}) is False

    def test_score_one_below_threshold_returns_false(self, condition):
        assert condition({"score": 74}, {}) is False

    def test_score_50_returns_false(self, condition):
        assert condition({"score": 50}, {}) is False

    def test_score_zero_returns_false(self, condition):
        assert condition({"score": 0}, {}) is False

    def test_score_negative_returns_false(self, condition):
        assert condition({"score": -10}, {}) is False

    # --- Missing / wrong key ---

    def test_missing_score_key_returns_false(self, condition):
        # dict.get("score", 0) returns 0 → 0 > 75 is False.
        assert condition({}, {}) is False

    def test_wrong_key_returns_false(self, condition):
        assert condition({"result": 80}, {}) is False

    def test_score_in_context_not_payload_returns_false(self, condition):
        # The condition reads payload only; context must not influence result.
        assert condition({}, {"score": 100}) is False

    # --- Context independence ---

    def test_populated_context_does_not_affect_passing_result(self, condition):
        assert condition({"score": 80}, {"score": 10, "other": "data"}) is True

    def test_populated_context_does_not_affect_failing_result(self, condition):
        assert condition({"score": 70}, {"score": 999}) is False

    # --- Custom threshold ---

    def test_custom_threshold_50_score_51_passes(self):
        cond = make_score_success_condition(50)
        assert cond({"score": 51}, {}) is True

    def test_custom_threshold_50_score_50_fails(self):
        cond = make_score_success_condition(50)
        assert cond({"score": 50}, {}) is False

    def test_custom_threshold_50_score_49_fails(self):
        cond = make_score_success_condition(50)
        assert cond({"score": 49}, {}) is False

    def test_threshold_zero_any_positive_score_passes(self):
        cond = make_score_success_condition(0)
        assert cond({"score": 1}, {}) is True

    def test_threshold_zero_score_zero_fails(self):
        cond = make_score_success_condition(0)
        assert cond({"score": 0}, {}) is False

    # --- Independent closures ---

    def test_two_closures_are_independent(self):
        cond_75 = make_score_success_condition(75)
        cond_90 = make_score_success_condition(90)
        payload = {"score": 80}
        assert cond_75(payload, {}) is True
        assert cond_90(payload, {}) is False

    def test_modifying_one_closure_threshold_does_not_affect_other(self):
        # Factory uses a closure, so each call creates a separate scope.
        cond_a = make_score_success_condition(60)
        cond_b = make_score_success_condition(80)
        assert cond_a({"score": 65}, {}) is True
        assert cond_b({"score": 65}, {}) is False


# ---------------------------------------------------------------------------
# make_interview_success_condition
# ---------------------------------------------------------------------------


class TestMakeInterviewSuccessCondition:
    """
    Tests for the interview success condition factory.

    Configured with the production decision string ("passed_interview"):
      decision == "passed_interview" → True
      anything else                 → False
    """

    @pytest.fixture
    def condition(self):
        """Production-configured condition: required_decision="passed_interview"."""
        return make_interview_success_condition("passed_interview")

    # --- Matching values ---

    def test_exact_decision_match_returns_true(self, condition):
        assert condition({"decision": "passed_interview"}, {}) is True

    # --- Non-matching values ---

    def test_wrong_decision_string_returns_false(self, condition):
        assert condition({"decision": "failed_interview"}, {}) is False

    def test_partial_match_returns_false(self, condition):
        assert condition({"decision": "passed"}, {}) is False

    def test_extra_suffix_returns_false(self, condition):
        assert condition({"decision": "passed_interview_2"}, {}) is False

    def test_empty_string_decision_returns_false(self, condition):
        assert condition({"decision": ""}, {}) is False

    # --- Case sensitivity ---

    def test_titlecase_returns_false(self, condition):
        assert condition({"decision": "Passed_Interview"}, {}) is False

    def test_uppercase_returns_false(self, condition):
        assert condition({"decision": "PASSED_INTERVIEW"}, {}) is False

    def test_mixed_case_returns_false(self, condition):
        assert condition({"decision": "Passed_interview"}, {}) is False

    # --- Missing / wrong key ---

    def test_missing_decision_key_returns_false(self, condition):
        # dict.get("decision") → None, which != "passed_interview".
        assert condition({}, {}) is False

    def test_wrong_key_returns_false(self, condition):
        assert condition({"result": "passed_interview"}, {}) is False

    def test_decision_in_context_not_payload_returns_false(self, condition):
        # The condition reads payload only.
        assert condition({}, {"decision": "passed_interview"}) is False

    # --- Context independence ---

    def test_populated_context_does_not_affect_passing_result(self, condition):
        assert (
            condition(
                {"decision": "passed_interview"},
                {"decision": "failed_interview", "score": 90},
            )
            is True
        )

    def test_populated_context_does_not_affect_failing_result(self, condition):
        assert condition({"decision": "failed"}, {"decision": "passed_interview"}) is False

    # --- Custom decision string ---

    def test_custom_decision_string_matches(self):
        cond = make_interview_success_condition("approved")
        assert cond({"decision": "approved"}, {}) is True

    def test_custom_decision_does_not_match_production_string(self):
        cond = make_interview_success_condition("approved")
        assert cond({"decision": "passed_interview"}, {}) is False

    # --- Independent closures ---

    def test_two_closures_are_independent(self):
        cond_a = make_interview_success_condition("passed_interview")
        cond_b = make_interview_success_condition("approved")
        payload = {"decision": "passed_interview"}
        assert cond_a(payload, {}) is True
        assert cond_b(payload, {}) is False

    def test_separate_factory_calls_do_not_share_state(self):
        cond_x = make_interview_success_condition("x")
        cond_y = make_interview_success_condition("y")
        assert cond_x({"decision": "x"}, {}) is True
        assert cond_y({"decision": "x"}, {}) is False
        assert cond_x({"decision": "y"}, {}) is False
        assert cond_y({"decision": "y"}, {}) is True


# ---------------------------------------------------------------------------
# make_max_attempts_condition
# ---------------------------------------------------------------------------


class TestMakeMaxAttemptsCondition:
    """
    Boundary analysis for the maximum-attempts condition.

    The condition reads ``context["{task_id}_attempts"]`` and returns True
    when the stored count is >= ``max_attempts``. Payload is never inspected.

    Configured with max_attempts=3 and task_id="perform_iq_test":
      attempts < 3  → False  (retry available)
      attempts == 3 → True   (limit reached — reject)
      attempts > 3  → True   (over limit — reject)
    """

    @pytest.fixture
    def condition(self):
        """Production-configured condition: max_attempts=3, task_id="perform_iq_test"."""
        return make_max_attempts_condition(3, "perform_iq_test")

    # --- Boundary: below limit ---

    def test_one_attempt_returns_false(self, condition):
        assert condition({}, {"perform_iq_test_attempts": 1}) is False

    def test_two_attempts_returns_false(self, condition):
        assert condition({}, {"perform_iq_test_attempts": 2}) is False

    # --- Boundary: at and above limit ---

    def test_exactly_at_max_returns_true(self, condition):
        assert condition({}, {"perform_iq_test_attempts": 3}) is True

    def test_above_max_returns_true(self, condition):
        assert condition({}, {"perform_iq_test_attempts": 4}) is True

    def test_far_above_max_returns_true(self, condition):
        assert condition({}, {"perform_iq_test_attempts": 100}) is True

    # --- Missing key defaults to zero ---

    def test_missing_attempts_key_returns_false(self, condition):
        # context.get(key, 0) → 0 < 3 → False.
        assert condition({}, {}) is False

    def test_wrong_task_key_in_context_returns_false(self, condition):
        # A counter for a different task must not satisfy this condition.
        assert condition({}, {"some_other_task_attempts": 10}) is False

    # --- Payload independence ---

    def test_payload_is_not_used(self, condition):
        # Even a payload with a large "score" should not influence the result.
        assert condition({"score": 999, "perform_iq_test_attempts": 5}, {"perform_iq_test_attempts": 1}) is False

    def test_attempts_in_payload_not_context_does_not_fire(self, condition):
        # The condition reads context, not payload.
        assert condition({"perform_iq_test_attempts": 5}, {}) is False

    # --- Custom thresholds ---

    def test_max_attempts_1_fires_on_first_attempt(self):
        cond = make_max_attempts_condition(1, "my_task")
        assert cond({}, {"my_task_attempts": 1}) is True

    def test_max_attempts_1_missing_key_returns_false(self):
        cond = make_max_attempts_condition(1, "my_task")
        assert cond({}, {}) is False

    def test_max_attempts_5_does_not_fire_at_4(self):
        cond = make_max_attempts_condition(5, "my_task")
        assert cond({}, {"my_task_attempts": 4}) is False

    def test_max_attempts_5_fires_at_5(self):
        cond = make_max_attempts_condition(5, "my_task")
        assert cond({}, {"my_task_attempts": 5}) is True

    # --- Independent closures (task_id isolation) ---

    def test_two_closures_with_different_task_ids_are_independent(self):
        cond_iq = make_max_attempts_condition(3, "perform_iq_test")
        cond_iv = make_max_attempts_condition(3, "perform_interview")
        context = {"perform_iq_test_attempts": 3, "perform_interview_attempts": 1}
        assert cond_iq({}, context) is True
        assert cond_iv({}, context) is False

    def test_two_closures_with_different_limits_are_independent(self):
        cond_3 = make_max_attempts_condition(3, "my_task")
        cond_5 = make_max_attempts_condition(5, "my_task")
        context = {"my_task_attempts": 3}
        assert cond_3({}, context) is True
        assert cond_5({}, context) is False
