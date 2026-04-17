"""Shared Pydantic schemas for Platform API request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Agent models
# ---------------------------------------------------------------------------

class AgentStatus(BaseModel):
    id: str
    port: int
    workspace: str
    domains: list[str]
    capabilities: list[str]
    supervisord_state: str | None = None  # RUNNING, STOPPED, etc.
    health: str | None = None             # ok, error
    uptime_s: float | None = None


class AgentCreateRequest(BaseModel):
    id: str
    port: int
    workspace: str
    telegram_token_env: str = ""
    telegram_chat_id_env: str = ""
    domains: list[str] = []
    capabilities: list[str] = []


# ---------------------------------------------------------------------------
# Task models
# ---------------------------------------------------------------------------

class TaskCreate(BaseModel):
    title: str
    description: str = ""
    priority: str = "normal"  # low, normal, high, urgent
    depends_on: list[UUID] = []
    assign_to: str | None = None
    created_by: str


class TaskPatch(BaseModel):
    status: str | None = None
    summary: str | None = None
    assigned_to: str | None = None


class TaskResponse(BaseModel):
    id: UUID
    parent_id: UUID | None
    title: str
    description: str | None
    created_by: str
    assigned_to: str | None
    assignment_mode: str
    status: str
    priority: str
    depends_on: list[UUID]
    retry_count: int
    max_retries: int
    summary: str | None
    created_at: datetime
    assigned_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None


# ---------------------------------------------------------------------------
# User / auth models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: UUID
    email: str
    name: str
    role: str


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class DomainCreate(BaseModel):
    name: str


class DomainGrant(BaseModel):
    agent_id: str
    mode: str = "read"  # read, write
