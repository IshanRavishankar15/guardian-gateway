import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, Uuid, func, literal_column, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    policies: Mapped[list["RateLimitPolicy"]] = relationship(back_populates="client")


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_client_id", "client_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped[Client] = relationship(back_populates="api_keys")


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (Index("ix_routes_enabled", "enabled"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    path_prefix: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    upstream_base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    methods: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=5.0, server_default="5")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class RateLimitPolicy(Base):
    __tablename__ = "rate_limit_policies"
    __table_args__ = (
        Index("ix_rate_limit_policies_client_id", "client_id"),
        Index("ix_rate_limit_policies_enabled", "enabled"),
        CheckConstraint("capacity > 0", name="ck_rate_limit_policies_capacity_positive"),
        CheckConstraint("refill_rate > 0", name="ck_rate_limit_policies_refill_positive"),
        Index(
            "uq_rate_limit_policy_global_scope", literal_column("(1)"), unique=True,
            postgresql_where=text("client_id IS NULL AND route_id IS NULL"),
        ),
        Index(
            "uq_rate_limit_policy_client_scope", "client_id", unique=True,
            postgresql_where=text("client_id IS NOT NULL AND route_id IS NULL"),
        ),
        Index(
            "uq_rate_limit_policy_route_scope", "route_id", unique=True,
            postgresql_where=text("client_id IS NULL AND route_id IS NOT NULL"),
        ),
        Index(
            "uq_rate_limit_policy_client_route_scope", "client_id", "route_id", unique=True,
            postgresql_where=text("client_id IS NOT NULL AND route_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clients.id", ondelete="CASCADE"))
    route_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("routes.id", ondelete="CASCADE"))
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    refill_rate: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    client: Mapped[Client | None] = relationship(back_populates="policies")
    route: Mapped[Route | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
