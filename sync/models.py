from typing import Any, Literal

from pydantic import BaseModel, Field


class SyncApplyRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    entity: str = Field(min_length=1, max_length=64)
    action: Literal["upsert", "delete"]
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(min_length=1)


class SyncApplyResponse(BaseModel):
    ok: bool
    enqueued: bool
    message: str
    event_id: str
    sequence: int


class SyncStatusResponse(BaseModel):
    nodo_id: str
    role: str
    sync: str
    last_applied_sequence: int
    queue: dict[str, int]
