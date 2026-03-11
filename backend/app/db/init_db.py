from sqlalchemy import text

from app.db.session import engine
from app.db.base import Base
import app.models.entities  # noqa: F401


def init_db():
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
