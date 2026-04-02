"""
In-memory persistence layer.

Provides UserStore, which manages the lifecycle of UserState objects
using a plain Python dictionary. 
all data lives in process memory and is reset on restart.

A module-level singleton (``user_store``) is exposed so that API
route handlers and other callers share a single store instance without
needing to manage dependency injection manually.
"""

import uuid
from typing import Dict

from app.core.flow_config import STARTING_STEP_ID, STARTING_TASK_ID
from app.models.schemas import UserState


class UserNotFoundError(KeyError):
    """Raised when a requested user_id is not present in the store."""


class UserStore:
    """
    Memory registry of UserState objects.

    Stores applicant journey state keyed by their unique user ID.

    Attributes:
        _users: Internal mapping from user_id to UserState.
    """

    def __init__(self) -> None:
        """Initialise the store with an empty user registry."""
        self._users: Dict[str, UserState] = {}

    def create_user(self, email: str) -> str:
        """
        Create a new applicant and register them at the start of the workflow.

        Generates a collision-resistant user ID, constructs a fresh UserState
        positioned at the workflow's entry point, and persists it to the store.

        Args:
            email: The applicant's email address. Stored in the initial context
                   so that downstream tasks (e.g. join_slack) can reference it
                   without requiring the caller to re-supply it.

        Returns:
            The newly generated user_id string.
        """
        user_id: str = uuid.uuid4().hex
        user = UserState(
            user_id=user_id,
            current_step_id=STARTING_STEP_ID,
            current_task_id=STARTING_TASK_ID,
            context={"email": email},
        )
        self._users[user_id] = user
        return user_id

    def get_user(self, user_id: str) -> UserState:
        """
        Retrieve an applicant's current journey state by their user ID.

        Args:
            user_id: The unique identifier returned by ``create_user``.

        Returns:
            The stored UserState for the given user_id.

        Raises:
            UserNotFoundError: If no user with the supplied user_id exists
                               in the store.
        """
        user: UserState | None = self._users.get(user_id)
        if user is None:
            raise UserNotFoundError(
                f"No user with id '{user_id}' found in the store."
            )
        return user

    def save_user(self, user: UserState) -> None:
        """
        Persist an updated UserState, overwriting the previous snapshot.

        The engine returns immutable UserState copies on every
        ``process_webhook`` call. Callers are responsible for passing those
        updated copies back to the store via this method so that progress
        is not lost between requests.

        Args:
            user: The updated UserState to persist. Its ``user_id`` is used
                  as the dictionary key; the previous snapshot is replaced.
        """
        self._users[user.user_id] = user


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Shared UserStore instance. Import this directly in route handlers and
#: other modules that need to read or write user journey state.
user_store = UserStore()
