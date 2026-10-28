from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Integer, String, Text, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    file_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(String, index=True)
    project_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    summary: Mapped[str] = mapped_column(Text, default="Investigation queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list] = mapped_column(JSON, default=list)
    diagnostics: Mapped[list] = mapped_column(JSON, default=list)
    patch: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    baseline: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now)
    updated_at: Mapped[str] = mapped_column(String, default=now)


class Activity(Base):
    __tablename__ = "activity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(String, index=True)
    type: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now)


def record(row: Base) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{(directory / 'rootcause.db').as_posix()}", connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def pragmas(connection: Any, _: Any) -> None:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def projects(self) -> list[dict]:
        with self.session() as session:
            return [record(row) for row in session.scalars(select(Project).order_by(Project.created_at.desc()))]

    def project(self, identity: str) -> dict | None:
        with self.session() as session:
            row = session.get(Project, identity)
            return record(row) if row else None

    def add_project(self, identity: str, name: str, file_count: int) -> dict:
        with self.session.begin() as session:
            row = Project(id=identity, name=name, file_count=file_count)
            session.add(row)
            session.flush()
            return record(row)

    def create(self, identity: str, project: dict) -> dict:
        with self.session.begin() as session:
            row = Investigation(id=identity, project_id=project["id"], project_name=project["name"])
            session.add(row)
            session.flush()
            return record(row)

    def list(self) -> list[dict]:
        with self.session() as session:
            rows = session.scalars(select(Investigation).order_by(Investigation.created_at.desc()).limit(200))
            return [{key: value for key, value in record(row).items() if key in {"id", "project_id", "project_name", "status", "summary", "created_at", "updated_at"}} for row in rows]

    def get(self, identity: str, include_events: bool = True) -> dict | None:
        with self.session() as session:
            row = session.get(Investigation, identity)
            if not row:
                return None
            result = record(row)
            if include_events:
                result["events"] = self.events(identity)
            return result

    def update(self, identity: str, **values: Any) -> dict:
        with self.session.begin() as session:
            row = session.get(Investigation, identity)
            if not row:
                raise ValueError("Investigation does not exist")
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = now()
            session.flush()
            return record(row)

    def emit(self, identity: str, kind: str, message: str, data: dict | None = None) -> dict:
        with self.session.begin() as session:
            row = Activity(investigation_id=identity, type=kind, message=message, data=data or {})
            session.add(row)
            session.flush()
            return record(row)

    def events(self, identity: str, after: int = 0) -> list[dict]:
        with self.session() as session:
            return [record(row) for row in session.scalars(select(Activity).where(Activity.investigation_id == identity, Activity.id > after).order_by(Activity.id))]
