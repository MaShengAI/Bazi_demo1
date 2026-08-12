from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str):
        engine_options: dict[str, object] = {"pool_pre_ping": True}
        if url.startswith("mysql"):
            engine_options["pool_recycle"] = 1800
        if url.startswith("sqlite"):
            engine_options["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(url, **engine_options)
        if url.startswith("sqlite"):
            event.listen(
                self.engine,
                "connect",
                lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
            )
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @classmethod
    def from_env(cls) -> Database | None:
        """The web app remains usable without a database; only persisted APIs are disabled."""
        url = os.getenv("BAZI_DATABASE_URL", "").strip()
        return cls(url) if url else None

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()

    def ping(self) -> None:
        with self.session() as session:
            session.execute(text("SELECT 1"))
