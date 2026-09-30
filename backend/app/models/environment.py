"""Environment database model definition."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import (
    Boolean,
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
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.service import Service


class Environment(Base):
    """Environment entity representing a runtime environment within a project (e.g., dev, staging, prod)."""

    __tablename__ = "environments"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_environments_project_id_slug"),
        UniqueConstraint("id", "project_id", "organization_id", name="uq_environments_id_project_org"),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_environments_project_organization",
            ondelete="RESTRICT",
        ),
        Index("ix_environments_organization_id", "organization_id"),
        Index("ix_environments_project_id", "project_id"),
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
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="environments",
        foreign_keys=[project_id],
    )
    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
    )
    services: Mapped[list["Service"]] = relationship(
        "Service",
        back_populates="environment",
        foreign_keys="[Service.environment_id]",
        lazy="selectin",
    )

    @validates("project")
    def validate_project(self, key: str, value: "Project | None") -> "Project | None":
        """Application-level validation ensuring environment and project share identical organization_id."""
        if value is not None and hasattr(self, "organization_id") and self.organization_id is not None:
            if value.organization_id != self.organization_id:
                raise ValueError("Environment organization_id must match project.organization_id")
        return value

    @validates("organization_id")
    def validate_organization_id(self, key: str, value: uuid.UUID) -> uuid.UUID:
        """Application-level validation ensuring organization_id matches project if project is attached."""
        if hasattr(self, "project") and self.project is not None:
            if self.project.organization_id != value:
                raise ValueError("Environment organization_id must match project.organization_id")
        return value

    def __repr__(self) -> str:
        return (
            f"<Environment id={self.id} org_id={self.organization_id} "
            f"project_id={self.project_id} slug={self.slug} is_active={self.is_active}>"
        )
