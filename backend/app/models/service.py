"""Service database model definition."""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.environment import Environment
    from app.models.organization import Organization
    from app.models.project import Project


class ServiceType(str, Enum):
    """Allowed initial service types for Phase 3."""

    APPLICATION = "APPLICATION"
    WORKER = "WORKER"
    DATABASE = "DATABASE"
    CACHE = "CACHE"
    QUEUE = "QUEUE"
    OTHER = "OTHER"


class Service(Base):
    """Service entity representing a distinct workload component within an environment."""

    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("environment_id", "slug", name="uq_services_environment_id_slug"),
        ForeignKeyConstraint(
            ["environment_id", "project_id", "organization_id"],
            ["environments.id", "environments.project_id", "environments.organization_id"],
            name="fk_services_environment_project_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "service_type IN ('APPLICATION', 'WORKER', 'DATABASE', 'CACHE', 'QUEUE', 'OTHER')",
            name="ck_services_service_type",
        ),
        Index("ix_services_organization_id", "organization_id"),
        Index("ix_services_project_id", "project_id"),
        Index("ix_services_environment_id", "environment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("environments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    service_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    environment: Mapped["Environment"] = relationship(
        "Environment",
        back_populates="services",
        foreign_keys=[environment_id],
    )
    project: Mapped["Project"] = relationship(
        "Project",
        foreign_keys=[project_id],
    )
    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
    )

    @validates("service_type")
    def validate_service_type(self, key: str, value: str | ServiceType) -> str:
        """Validate that service_type is among the allowed ServiceType enum values."""
        str_val = value.value if isinstance(value, ServiceType) else str(value)
        allowed = {t.value for t in ServiceType}
        if str_val not in allowed:
            raise ValueError(
                f"Invalid service_type: '{str_val}'. Must be one of {sorted(allowed)}"
            )
        return str_val

    @validates("environment")
    def validate_environment(self, key: str, value: "Environment | None") -> "Environment | None":
        """Application-level validation ensuring service hierarchy matches environment."""
        if value is not None:
            if hasattr(self, "organization_id") and self.organization_id is not None:
                if value.organization_id != self.organization_id:
                    raise ValueError("Service organization_id must match environment.organization_id")
            if hasattr(self, "project_id") and self.project_id is not None:
                if value.project_id != self.project_id:
                    raise ValueError("Service project_id must match environment.project_id")
        return value

    def __repr__(self) -> str:
        return (
            f"<Service id={self.id} org_id={self.organization_id} "
            f"project_id={self.project_id} env_id={self.environment_id} "
            f"slug={self.slug} type={self.service_type} is_active={self.is_active}>"
        )
