"""Genre model."""

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from sonicverse.core.database import Base


class Genre(Base):
    """Genre entity."""

    __tablename__ = "genres"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<Genre(id={self.id}, name={self.name})>"
