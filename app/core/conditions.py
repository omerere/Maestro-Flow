"""

This module owns the admissions business rules that govern how an applicant
progresses through the workflow graph.

Condition factories return closures that are assigned to Outcome.condition
fields in flow_config.py.
"""

from typing import Any, Callable, Dict


# ---------------------------------------------------------------------------
# Condition factories
# ---------------------------------------------------------------------------


def make_score_success_condition(
    min_passing_score: int,
) -> Callable[[Dict[str, Any], Dict[str, Any]], bool]:
    """
    Factory that produces a condition callable for IQ score success.

    Closing over ``min_passing_score`` allows the threshold to be configured
    at graph-construction time without hardcoding it inside the condition.
    
    Args:
        min_passing_score: Scores strictly above this value are treated as a
                           pass and trigger an explicit fallthrough to the
                           step-level router.

    Returns:
        A callable ``(payload, context) -> bool`` that returns True when
        ``payload["score"]`` is present and > ``min_passing_score``.
    """

    def _condition(payload: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Return True if the applicant's IQ score represents a pass."""
        return payload.get("score", 0) > min_passing_score

    return _condition


def make_interview_success_condition(
    required_decision: str,
) -> Callable[[Dict[str, Any], Dict[str, Any]], bool]:
    """
    Factory that produces a condition callable for interview success.

    Closing over ``required_decision`` keeps the expected decision string
    configurable without magic values inside the condition body.

    Args:
        required_decision: The exact ``decision`` value the external system
                           must supply to indicate a passing interview.

    Returns:
        A callable ``(payload, context) -> bool`` that returns True when
        ``payload["decision"]`` == ``required_decision``.
    """

    def _condition(payload: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Return True if the applicant's interview decision represents a pass."""
        return payload.get("decision") == required_decision

    return _condition


def make_max_attempts_condition(
    max_attempts: int,
    task_id: str,
) -> Callable[[Dict[str, Any], Dict[str, Any]], bool]:
    """
    Factory that produces a condition callable for maximum retry enforcement.

    Closing over ``max_attempts`` and ``task_id`` allows the retry limit to be
    configured at graph-construction time without hardcoding values inside the
    condition body. The engine increments the attempt counter in the user
    context (via ``_merge_context``) *before* Outcomes are evaluated, so when
    this condition is checked the counter already reflects the current attempt.

    When this condition matches, the paired Outcome carries a terminal
    ``status="rejected"`` routing target, ending the applicant's journey once
    the retry ceiling is reached.

    Args:
        max_attempts: The inclusive upper bound on allowed submissions. The
                      condition returns ``True`` when the stored attempt count
                      is >= this value, triggering the rejection Outcome.
        task_id:      The ID of the TaskNode whose attempt counter is tracked.
                      The context key is derived as ``f"{task_id}_attempts"``.

    Returns:
        A callable ``(payload, context) -> bool`` that returns ``True`` when
        ``context["{task_id}_attempts"]`` >= ``max_attempts``.
    """

    def _condition(payload: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Return True if the applicant has exhausted their allowed attempts."""
        return context.get(f"{task_id}_attempts", 0) >= max_attempts

    return _condition
