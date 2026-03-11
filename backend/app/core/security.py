from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
        except ValueError:
            return False
    try:
        return pwd_context.verify(password, hashed_password)
    except Exception:
        return False


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    expires_delta = timedelta(minutes=expires_minutes or settings.jwt_expires_min)
    to_encode = {"sub": subject, "exp": datetime.utcnow() + expires_delta}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
        return payload.get("sub")
    except JWTError:
        return None
