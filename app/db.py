from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal = sessionmaker(expire_on_commit=False)


def init_db(url: str | None = None, reset: bool = False):
    """Create (or switch to) a database. Tests and eval call this with a temp URL."""
    global _engine
    from app.models import case  # noqa: F401  (register tables)

    url = url or config.DB_URL
    _engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    SessionLocal.configure(bind=_engine)
    if reset:
        Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    return _engine


def get_engine():
    if _engine is None:
        init_db()
    return _engine


@contextmanager
def session_scope():
    get_engine()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
