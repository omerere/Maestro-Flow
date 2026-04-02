"""
Unit tests for UserStore in app.core.store.

Each test uses a freshly constructed UserStore instance (not the module
singleton) to guarantee complete isolation — no state leaks between tests
regardless of execution order.

Coverage:
  create_user  — ID uniqueness, initial position, email in context, status.
  get_user     — successful retrieval, UserNotFoundError for unknown IDs.
  save_user    — overwrites previous snapshot, non-destructive to other users.
"""

import pytest

from app.core.flow_config import STARTING_STEP_ID, STARTING_TASK_ID
from app.core.store import UserNotFoundError, UserStore
from app.models.schemas import UserState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> UserStore:
    """Return a fresh, empty UserStore for each test."""
    return UserStore()


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


class TestCreateUser:
    def test_returns_a_non_empty_string_id(self, store):
        user_id = store.create_user(email="alice@test.com")
        assert isinstance(user_id, str)
        assert len(user_id) > 0

    def test_returned_id_can_immediately_retrieve_the_user(self, store):
        user_id = store.create_user(email="alice@test.com")
        user = store.get_user(user_id)
        assert user.user_id == user_id

    def test_user_initial_step_is_starting_step(self, store):
        user_id = store.create_user(email="alice@test.com")
        user = store.get_user(user_id)
        assert user.current_step_id == STARTING_STEP_ID

    def test_user_initial_task_is_starting_task(self, store):
        user_id = store.create_user(email="alice@test.com")
        user = store.get_user(user_id)
        assert user.current_task_id == STARTING_TASK_ID

    def test_email_is_stored_in_initial_context(self, store):
        user_id = store.create_user(email="bob@example.com")
        user = store.get_user(user_id)
        assert user.context.get("email") == "bob@example.com"

    def test_initial_status_is_in_progress(self, store):
        user_id = store.create_user(email="carol@test.com")
        user = store.get_user(user_id)
        assert user.status == "in_progress"

    def test_two_calls_produce_different_ids(self, store):
        id_a = store.create_user(email="a@test.com")
        id_b = store.create_user(email="b@test.com")
        assert id_a != id_b

    def test_multiple_users_are_independent(self, store):
        id_a = store.create_user(email="a@test.com")
        id_b = store.create_user(email="b@test.com")
        assert store.get_user(id_a).context["email"] == "a@test.com"
        assert store.get_user(id_b).context["email"] == "b@test.com"

    def test_store_size_grows_with_each_creation(self, store):
        assert len(store._users) == 0
        store.create_user(email="x@test.com")
        assert len(store._users) == 1
        store.create_user(email="y@test.com")
        assert len(store._users) == 2


# ---------------------------------------------------------------------------
# get_user
# ---------------------------------------------------------------------------


class TestGetUser:
    def test_returns_correct_user_state(self, store):
        user_id = store.create_user(email="dave@test.com")
        user = store.get_user(user_id)
        assert isinstance(user, UserState)
        assert user.user_id == user_id

    def test_returns_same_object_as_stored(self, store):
        user_id = store.create_user(email="eve@test.com")
        user_a = store.get_user(user_id)
        user_b = store.get_user(user_id)
        # Both retrievals must refer to the same stored state.
        assert user_a == user_b

    def test_raises_user_not_found_error_for_unknown_id(self, store):
        with pytest.raises(UserNotFoundError):
            store.get_user("this-id-does-not-exist")

    def test_user_not_found_error_is_subclass_of_key_error(self, store):
        with pytest.raises(KeyError):
            store.get_user("ghost")

    def test_raises_for_empty_string_id(self, store):
        with pytest.raises(UserNotFoundError):
            store.get_user("")

    def test_raises_for_id_that_was_never_created(self, store):
        store.create_user(email="real@test.com")  # populate the store
        with pytest.raises(UserNotFoundError):
            store.get_user("completely-fake-id")

    def test_does_not_raise_after_user_is_created(self, store):
        user_id = store.create_user(email="frank@test.com")
        # Must not raise — user exists.
        user = store.get_user(user_id)
        assert user is not None


# ---------------------------------------------------------------------------
# save_user
# ---------------------------------------------------------------------------


class TestSaveUser:
    def test_overwrites_previous_snapshot(self, store):
        user_id = store.create_user(email="grace@test.com")
        original = store.get_user(user_id)

        updated = original.model_copy(update={"status": "accepted"})
        store.save_user(updated)

        retrieved = store.get_user(user_id)
        assert retrieved.status == "accepted"

    def test_updated_step_id_is_persisted(self, store):
        user_id = store.create_user(email="harry@test.com")
        original = store.get_user(user_id)

        updated = original.model_copy(update={"current_step_id": "iq_step"})
        store.save_user(updated)

        assert store.get_user(user_id).current_step_id == "iq_step"

    def test_updated_task_id_is_persisted(self, store):
        user_id = store.create_user(email="irene@test.com")
        original = store.get_user(user_id)

        updated = original.model_copy(update={"current_task_id": "perform_iq_test"})
        store.save_user(updated)

        assert store.get_user(user_id).current_task_id == "perform_iq_test"

    def test_updated_context_is_persisted(self, store):
        user_id = store.create_user(email="jack@test.com")
        original = store.get_user(user_id)

        new_context = {**original.context, "score": 88}
        updated = original.model_copy(update={"context": new_context})
        store.save_user(updated)

        assert store.get_user(user_id).context["score"] == 88

    def test_save_does_not_affect_other_users(self, store):
        id_a = store.create_user(email="aa@test.com")
        id_b = store.create_user(email="bb@test.com")

        user_a = store.get_user(id_a)
        updated_a = user_a.model_copy(update={"status": "rejected"})
        store.save_user(updated_a)

        # User B must be completely unaffected.
        assert store.get_user(id_b).status == "in_progress"

    def test_multiple_saves_each_overwrite_the_previous(self, store):
        user_id = store.create_user(email="kelly@test.com")
        base = store.get_user(user_id)

        store.save_user(base.model_copy(update={"status": "in_progress"}))
        store.save_user(base.model_copy(update={"status": "accepted"}))
        store.save_user(base.model_copy(update={"status": "rejected"}))

        assert store.get_user(user_id).status == "rejected"

    def test_store_size_does_not_grow_on_save(self, store):
        user_id = store.create_user(email="leo@test.com")
        assert len(store._users) == 1

        updated = store.get_user(user_id).model_copy(update={"status": "accepted"})
        store.save_user(updated)

        assert len(store._users) == 1
