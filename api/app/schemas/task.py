import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Request schemas ────────────────────────────────────────


_PAYLOAD_MAX_BYTES = 32_768  # 32 KB


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    task_type: str = Field(..., min_length=1, max_length=100)
    payload: dict[str, Any] | None = None
    n8n_execution_id: str | None = None

    @field_validator("payload")
    @classmethod
    def check_payload_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v)) > _PAYLOAD_MAX_BYTES:
            raise ValueError(f"payload exceeds {_PAYLOAD_MAX_BYTES // 1024}KB limit")
        return v


_VALID_STATUSES = {"pending", "running", "success", "failed", "cancelled"}


class TaskUpdate(BaseModel):
    status: str | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None
    n8n_execution_id: str | None = None

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"Invalid status '{v}'. Must be one of: {sorted(_VALID_STATUSES)}")
        return v

    @field_validator("result")
    @classmethod
    def check_result_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v)) > _PAYLOAD_MAX_BYTES:
            raise ValueError(f"result exceeds {_PAYLOAD_MAX_BYTES // 1024}KB limit")
        return v


# ── Response schemas ───────────────────────────────────────


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    task_type: str
    status: str
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    error_message: str | None
    n8n_execution_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
    page: int
    size: int
