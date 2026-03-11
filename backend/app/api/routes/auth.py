from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.core.rbac import ROLE_ORG_ADMIN
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import Tenant, User, Workspace
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest

router = APIRouter()


def ensure_default_tenant(db: Session) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.name == "default").first()
    if not tenant:
        tenant = Tenant(name="default")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    return tenant


def ensure_default_workspace(db: Session, tenant_id: str) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.tenant_id == tenant_id).first()
    if not ws:
        ws = Workspace(tenant_id=tenant_id, name="default")
        db.add(ws)
        db.commit()
        db.refresh(ws)
    return ws


@router.post("/register", response_model=LoginResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db_session)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    tenant = ensure_default_tenant(db)
    ensure_default_workspace(db, tenant.id)
    user = User(
        tenant_id=tenant.id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        roles_json=[ROLE_ORG_ADMIN],
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.email)
    return LoginResponse(access_token=token)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db_session)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.hashed_password and not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(subject=user.email)
    return LoginResponse(access_token=token)
