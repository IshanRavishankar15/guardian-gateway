import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class ClientRead(ORMModel):
    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime


class APIKeyRead(ORMModel):
    id: uuid.UUID
    client_id: uuid.UUID
    key_prefix: str
    created_at: datetime
    revoked_at: datetime | None


class APIKeyCreated(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    key_prefix: str
    api_key: str = Field(description="Shown only once. Store securely; it cannot be retrieved later.")
    created_at: datetime


class RouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path_prefix: str = Field(min_length=1, max_length=255)
    upstream_base_url: str = Field(min_length=8, max_length=2048)
    methods: list[Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]] = Field(min_length=1)
    timeout_seconds: float = Field(default=5.0, gt=0, le=120, allow_inf_nan=False)
    enabled: bool = True

    @field_validator("path_prefix")
    @classmethod
    def path_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "?" in value or "#" in value:
            raise ValueError("path_prefix must be an absolute path without query or fragment")
        return value.rstrip("/") or "/"

    @field_validator("upstream_base_url")
    @classmethod
    def upstream_must_be_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("upstream_base_url must be an HTTP(S) URL without embedded credentials")
        if parsed.hostname.rstrip(".").lower() not in get_settings().upstream_host_allowlist:
            raise ValueError("upstream host is not in ALLOWED_UPSTREAM_HOSTS")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("upstream_base_url contains an invalid port") from exc
        if parsed.query or parsed.fragment:
            raise ValueError("upstream_base_url cannot contain a query or fragment")
        return value.rstrip("/")


class RouteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    path_prefix: str | None = Field(default=None, min_length=1, max_length=255)
    upstream_base_url: str | None = Field(default=None, min_length=8, max_length=2048)
    methods: list[Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]] | None = Field(default=None, min_length=1)
    timeout_seconds: float | None = Field(default=None, gt=0, le=120, allow_inf_nan=False)
    enabled: bool | None = None

    @field_validator("path_prefix")
    @classmethod
    def path_must_be_absolute(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("/") or value.startswith("//") or "?" in value or "#" in value):
            raise ValueError("path_prefix must be an absolute path without query or fragment")
        if value is None:
            return None
        return value.rstrip("/") or "/"

    @field_validator("upstream_base_url")
    @classmethod
    def upstream_must_be_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("upstream_base_url must be an HTTP(S) URL without credentials, query, or fragment")
        if parsed.hostname.rstrip(".").lower() not in get_settings().upstream_host_allowlist:
            raise ValueError("upstream host is not in ALLOWED_UPSTREAM_HOSTS")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("upstream_base_url contains an invalid port") from exc
        return value.rstrip("/")


class RouteRead(ORMModel):
    id: uuid.UUID
    name: str
    path_prefix: str
    upstream_base_url: str
    methods: list[str]
    timeout_seconds: float
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    client_id: uuid.UUID | None = None
    route_id: uuid.UUID | None = None
    capacity: int = Field(gt=0, le=1_000_000)
    refill_rate: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    enabled: bool = True


class PolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    client_id: uuid.UUID | None = None
    route_id: uuid.UUID | None = None
    capacity: int | None = Field(default=None, gt=0, le=1_000_000)
    refill_rate: float | None = Field(default=None, gt=0, le=100_000, allow_inf_nan=False)
    enabled: bool | None = None


class PolicyRead(ORMModel):
    id: uuid.UUID
    name: str
    client_id: uuid.UUID | None
    route_id: uuid.UUID | None
    capacity: int
    refill_rate: float
    enabled: bool
    created_at: datetime
    updated_at: datetime
