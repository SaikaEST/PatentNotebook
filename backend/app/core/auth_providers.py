from typing import Protocol, Optional

from app.core.security import create_access_token


class AuthProvider(Protocol):
    name: str

    def authenticate(self, email: str, password: str) -> Optional[str]:
        ...


class LocalProvider:
    name = "local"

    def authenticate(self, email: str, password: str) -> Optional[str]:
        return create_access_token(subject=email)


class OIDCProvider:
    name = "oidc"

    def authenticate(self, email: str, password: str) -> Optional[str]:
        return None


class SAMLProvider:
    name = "saml"

    def authenticate(self, email: str, password: str) -> Optional[str]:
        return None
