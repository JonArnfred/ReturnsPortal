"""UI preference endpoints: saved default filters per page."""

from __future__ import annotations

from datetime import datetime

from litestar import delete, get, put
from litestar.exceptions import NotFoundException, ValidationException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromPath
from pydantic import BaseModel, Field

from app.openapi import standard_error_responses
from app.services import preference_service

KEY_DESCRIPTION = "Preference key, <kind>:<name>, e.g. filters:orders."


class Preference(BaseModel):
    key: str = Field(description=KEY_DESCRIPTION, examples=["filters:orders"])
    value: dict[str, str] = Field(description="Filter values by filter name.", examples=[{"status": "open"}])
    updated_at: datetime


class PreferencesResponse(BaseModel):
    data: list[Preference]


class PreferenceUpdate(BaseModel):
    value: dict[str, str] = Field(description="Filter values by filter name; replaces the stored value.")


def _check_key(key: str) -> None:
    if not preference_service.valid_key(key):
        raise ValidationException(detail=f"invalid preference key {key!r}; expected <kind>:<name>")


@get(
    "/api/preferences",
    operation_id="listPreferences",
    summary="List UI preferences",
    description="Every stored preference, such as the saved default filters per page. Read-only.",
    responses={
        200: ResponseSpec(data_container=PreferencesResponse, description="Preferences by key."),
        **standard_error_responses(),
    },
    tags=["Preferences"],
    sync_to_thread=True,
)
def list_preferences() -> PreferencesResponse:
    return PreferencesResponse(data=[Preference.model_validate(row) for row in preference_service.list_preferences()])


@put(
    "/api/preferences/{key:str}",
    operation_id="savePreference",
    summary="Save a UI preference",
    description="Stores the value under the key, replacing any previous value. Used to save a page's default filters.",
    responses={
        200: ResponseSpec(data_container=Preference, description="The stored preference."),
        **standard_error_responses(),
    },
    tags=["Preferences"],
    sync_to_thread=True,
)
def save_preference(key: FromPath[str], data: PreferenceUpdate) -> Preference:
    _check_key(key)
    return Preference.model_validate(preference_service.save_preference(key, data.value))


@delete(
    "/api/preferences/{key:str}",
    operation_id="deletePreference",
    summary="Delete a UI preference",
    description="Removes the stored value so the page falls back to its built-in defaults. 404 when nothing is stored.",
    status_code=204,
    responses={204: ResponseSpec(data_container=None, description="Deleted."), **standard_error_responses()},
    tags=["Preferences"],
    sync_to_thread=True,
)
def delete_preference(key: FromPath[str]) -> None:
    _check_key(key)
    if not preference_service.delete_preference(key):
        raise NotFoundException(detail=f"no preference stored under {key!r}")


routes = [list_preferences, save_preference, delete_preference]
