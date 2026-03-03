from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True) 
    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="free")  
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="user")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.user_id"), nullable=False)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)   
    price: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  
    mode: Mapped[str] = mapped_column(String(8), nullable=False)     

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_user_active", "user_id", "is_active"),
        Index("ix_alerts_symbol_active", "symbol", "is_active"),
        Index("ix_alerts_active", "is_active"),
        UniqueConstraint("user_id", "symbol", "price", "direction", "mode", name="uq_alert_dedupe"),
    )