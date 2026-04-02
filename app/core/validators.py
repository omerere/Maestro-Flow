"""
Payload validator callables.

Each validator is a pure function that receives the raw ``payload`` dict
from an incoming webhook and returns True if all required keys are present.
Validators are assigned to TaskNode instances in flow_config.py and are
executed by the WorkflowEngine before any Outcome conditions are evaluated.

"""

from typing import Any, Dict


def validate_iq_score(payload: Dict[str, Any]) -> bool:
    """
    Validate that an IQ test submission contains a numeric score.

    Args:
        payload: Raw submission dict from the incoming webhook.

    Returns:
        True if "score" is present in the payload, False otherwise.
    """
    return "score" in payload


def validate_personal_details(payload: Dict[str, Any]) -> bool:
    """
    Validate that a personal-details submission contains the required fields.

    Args:
        payload: Raw submission dict from the incoming webhook.

    Returns:
        True if "first_name", "last_name", and "email" are all present.
    """
    return all(key in payload for key in ("first_name", "last_name", "email"))


def validate_schedule_interview(payload: Dict[str, Any]) -> bool:
    """
    Validate that an interview-scheduling submission contains a date.

    Args:
        payload: Raw submission dict from the incoming webhook.

    Returns:
        True if "interview_date" is present in the payload.
    """
    return "interview_date" in payload


def validate_perform_interview(payload: Dict[str, Any]) -> bool:
    """
    Validate that an interview-result submission contains a decision.

    Args:
        payload: Raw submission dict from the incoming webhook.

    Returns:
        True if "decision" is present in the payload.
    """
    return "decision" in payload


def validate_upload_id(payload: Dict[str, Any]) -> bool:
    """
    Validate that an ID-upload submission contains a passport number.

    Args:
        payload: Raw submission dict from the incoming webhook.

    Returns:
        True if "passport_number" is present in the payload.
    """
    return "passport_number" in payload


def validate_payment(payload: Dict[str, Any]) -> bool:
    """
    Validate that a payment submission contains a payment identifier.

    Args:
        payload: Raw submission dict from the incoming webhook.

    Returns:
        True if "payment_id" is present in the payload.
    """
    return "payment_id" in payload


def validate_join_slack(payload: Dict[str, Any]) -> bool:
    """
    Validate that a Slack-join submission contains an email address.

    Args:
        payload: Raw submission dict from the incoming webhook.

    Returns:
        True if "email" is present in the payload.
    """
    return "email" in payload


