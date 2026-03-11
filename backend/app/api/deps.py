from typing import Generator

from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import decode_access_token
from app.models.entities import User


def get_db_session() -> Generator:
    yield from get_db()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    subject = decode_access_token(token)
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.email == subject).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
